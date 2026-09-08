"""EA-312 grounded, fail-closed air-pollution response planning.

The corpus combines Israeli particulate guidance with explicitly scoped
international pollutant guidance. Missing, out-of-scope, or merely reference
material fails closed before Claude. Recommendations must match reviewed
manifest actions as well as cite retrieved source passages.
"""

import json

from pydantic import ValidationError

from agents.air_pollution_anomaly_schemas import AirPollutionAnomaly
from agents.air_pollution_correlation import (
    PollutionCorrelationCandidate, PollutionCorrelationResult, correlation_candidate,
)
from agents.air_pollution_response_schemas import (
    AirPollutionPlanProposal, AirPollutionPlanningResult, AirPollutionResponsePlan,
)
from agents.air_pollution_spatial_schemas import SpatiallyEnrichedAirPollutionAnomaly
from agents.risk_analysis_agent import render_excerpts
from services.claude_llm_service import (
    ClaudeLLMService, ClaudeProviderError, build_system_blocks,
)
from services.protocol_retrieval_service import (
    ProtocolRetriever, normalize_for_match, verify_citations,
)

SYSTEM_PROMPT = """\
You are EcoGuard's air-pollution response-planning component. Produce decision-support
recommendations, not operational commands, using only the supplied anomaly evidence and
air-pollution guidance excerpts.

Strict rules:
- Do not classify an emergency, confirm exposure or health impact, identify a pollution
  source, allocate a facility, claim availability, dispatch, or invent resource quantities.
- Nearby places and facilities are context only; they do not prove exposure.
- Preliminary measurements remain preliminary. Preserve all evidence gaps and limitations.
- Every action must cite one or more supplied chunk IDs in supporting_chunk_ids.
- Every protocol citation must quote the supplied chunk verbatim and use its exact chunk ID.
- Do not recommend an action that the supplied excerpts do not support. If guidance is
  narrower than the event, state that limitation instead of generalising it.
- Choose actions only from the reviewed action list, copying all five fields exactly.
  Add supporting_chunk_ids and quote the COMPLETE recommendation passage as a citation.
  Preserve every condition. An anomaly severity is not an official advisory category.
  Do not invent deadlines or priority where the reviewed action says not_specified.
"""


class AirPollutionResponsePlanner:
    """Separate from FireCoordinator and storage/network collection layers."""

    def __init__(self, *, llm_service=None, retriever=None, top_k: int = 5):
        self.llm_service = llm_service if llm_service is not None else ClaudeLLMService()
        self.retriever = (
            retriever
            if retriever is not None
            else ProtocolRetriever(hazard="air_pollution")
        )
        self.top_k = top_k

    def plan_response(
        self,
        event: AirPollutionAnomaly | SpatiallyEnrichedAirPollutionAnomaly | PollutionCorrelationCandidate,
        *, correlation_evidence: PollutionCorrelationResult | None = None,
    ) -> AirPollutionPlanningResult:
        candidate = self._candidate(event)
        limitations = self._context_limitations(candidate, correlation_evidence)
        if correlation_evidence is not None and candidate.anomaly not in (
            correlation_evidence.left.anomaly, correlation_evidence.right.anomaly
        ):
            return self._result(
                candidate, correlation_evidence, "failed",
                "correlation_context_mismatch", limitations,
            )
        if not candidate.anomaly.pollutant_observations:
            return self._result(
                candidate, correlation_evidence, "skipped",
                "insufficient_anomaly_evidence", limitations,
            )
        if getattr(self.retriever, "hazard", None) != "air_pollution":
            return self._result(
                candidate, correlation_evidence, "failed",
                "guidance_scope_mismatch", limitations,
            )

        try:
            documents = getattr(self.retriever, "documents", {})
            # The corpus is deliberately small. Retrieve enough candidates to
            # keep reference-only documents from displacing the one reviewed
            # action document, then apply the strict pollutant/action filters.
            retrieval_limit = max(
                self.top_k,
                len(getattr(self.retriever, "chunks", [])),
                len(documents),
            )
            chunks = self.retriever.retrieve(
                self._query(candidate), top_k=retrieval_limit,
            )
            chunks = [chunk for chunk in chunks if set(candidate.pollutants).issubset(
                set(documents.get(chunk["document_id"], {}).get("supported_pollutants", []))
            )]
            reviewed = self._reviewed_actions(chunks, documents)
            if not reviewed:
                chunks = []
        except Exception:
            chunks = []
        if not chunks:
            return self._result(
                candidate, correlation_evidence, "failed",
                "guidance_unavailable", limitations,
            )
        if not getattr(self.llm_service, "available", False):
            return self._result(
                candidate, correlation_evidence, "failed",
                "model_unavailable", limitations,
            )

        try:
            proposal = self.llm_service.parse_structured(
                system_blocks=build_system_blocks(SYSTEM_PROMPT),
                user_text=self._prompt(candidate, correlation_evidence, chunks, reviewed),
                output_format=AirPollutionPlanProposal,
            )
        except ClaudeProviderError:
            return self._result(candidate, correlation_evidence, "failed", "model_failure", limitations)
        try:
            proposal = AirPollutionPlanProposal.model_validate(
                proposal.model_dump() if isinstance(proposal, AirPollutionPlanProposal) else proposal
            )
        except (ValidationError, TypeError, AttributeError):
            return self._result(
                candidate, correlation_evidence, "failed",
                "malformed_output", limitations,
            )

        payload = proposal.model_dump(mode="json")
        citations, dropped = verify_citations(payload["protocol_citations"], chunks)
        verified_ids = {citation["chunk_id"] for citation in citations}
        action_ids = {
            chunk_id
            for action in proposal.actions
            for chunk_id in action.supporting_chunk_ids
        }
        if (
            dropped or not citations or not action_ids.issubset(verified_ids)
            or not self._actions_grounded(proposal, reviewed, citations)
        ):
            return self._result(
                candidate, correlation_evidence, "failed",
                "ungrounded_response", limitations,
            )

        combined_limitations = list(dict.fromkeys([*proposal.limitations, *limitations]))
        plan = AirPollutionResponsePlan(
            # Keep actionable prose constrained to reviewed recommendations;
            # the model cannot smuggle unsupported instructions into a summary.
            status="success", summary=" ".join(action.recommendation for action in proposal.actions),
            recommended_authority_types=proposal.recommended_authority_types,
            recommended_resource_types=proposal.recommended_resource_types,
            actions=proposal.actions, assumptions=proposal.assumptions,
            evidence_gaps=proposal.evidence_gaps, limitations=combined_limitations,
            protocol_references=citations,
        )
        return AirPollutionPlanningResult(
            event=candidate, correlation_evidence=correlation_evidence, plan=plan,
        )

    @staticmethod
    def _candidate(event):
        if isinstance(event, PollutionCorrelationCandidate):
            return PollutionCorrelationCandidate.model_validate(event.model_dump(round_trip=True))
        return correlation_candidate(event)

    @staticmethod
    def _query(candidate):
        anomaly = candidate.anomaly
        pollutants = " ".join(candidate.pollutants)
        return (
            f"air pollution {pollutants} {anomaly.severity} response "
            "public health advisory monitoring"
        )

    @staticmethod
    def _prompt(candidate, correlation_evidence, chunks, reviewed):
        event_json = json.dumps(
            candidate.model_dump(mode="json"), ensure_ascii=False, indent=2,
        )
        correlation_json = (
            json.dumps(
                correlation_evidence.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            if correlation_evidence is not None
            else "Not supplied; do not infer multi-event confirmation."
        )
        return (
            f"# Correlation-ready pollution event\n{event_json}\n\n"
            f"# Optional correlation evidence\n{correlation_json}\n\n"
            "# Verified pollution-guidance excerpts\n"
            f"{render_excerpts(chunks)}\n\n"
            "# Reviewed actions (exact wording and fields required)\n"
            f"{json.dumps(reviewed, ensure_ascii=False)}\n\n"
            "# Task\nReturn only recommendations supported by these excerpts."
        )

    @staticmethod
    def _reviewed_actions(chunks, documents):
        """Only offer manifest actions whose entire passage was retrieved."""
        reviewed = []
        for chunk in chunks:
            for action in documents[chunk["document_id"]].get("reviewed_actions", []):
                if normalize_for_match(action["recommendation"]) in normalize_for_match(chunk["text"]):
                    reviewed.append({**action, "supporting_chunk_ids": [chunk["chunk_id"]]})
        return reviewed

    @staticmethod
    def _actions_grounded(proposal, reviewed, citations):
        # Quote existence alone does not establish support for an instruction.
        # Check exact reviewed semantics (including conditions/type/timeframe)
        # and the full passage, in addition to the shared citation verifier.
        fields = ("recommendation", "responsible_authority_type", "resource_type", "timeframe", "priority")
        for action in proposal.actions:
            if not any(
                all(getattr(action, field) == approved[field] for field in fields)
                and set(action.supporting_chunk_ids).issubset(approved["supporting_chunk_ids"])
                for approved in reviewed
            ):
                return False
            if not any(
                citation["chunk_id"] in action.supporting_chunk_ids
                and normalize_for_match(action.recommendation) in normalize_for_match(citation["quoted_text"])
                for citation in citations
            ):
                return False
        return (
            set(proposal.recommended_authority_types)
            == {action.responsible_authority_type for action in proposal.actions}
            and set(proposal.recommended_resource_types)
            == {action.resource_type for action in proposal.actions}
        )

    @staticmethod
    def _context_limitations(candidate, correlation_evidence):
        limitations = [
            "Decision support only; no authority acceptance, resource availability, "
            "allocation or dispatch is represented."
        ]
        context = candidate.spatial_context
        if context is None:
            limitations.append(
                "No spatial context was supplied; nearby populations or facilities "
                "were not inferred."
            )
        elif context.status != "success":
            limitations.append(
                "Spatial context is partial or unavailable; nearby-feature absence "
                "is not conclusive."
            )
        if candidate.anomaly.assessment and candidate.anomaly.assessment.preliminary:
            limitations.append(
                "The anomaly uses preliminary observations that have not completed "
                "provider quality control."
            )
        if correlation_evidence is None:
            limitations.append(
                "No correlation evidence was supplied; the plan does not assume "
                "multi-event confirmation."
            )
        return limitations

    @staticmethod
    def _result(candidate, correlation_evidence, status, reason, limitations):
        return AirPollutionPlanningResult(
            event=candidate, correlation_evidence=correlation_evidence,
            plan=AirPollutionResponsePlan(status=status, reason=reason, limitations=limitations),
        )
