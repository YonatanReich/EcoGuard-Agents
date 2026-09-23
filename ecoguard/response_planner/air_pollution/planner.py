"""Fail-closed, protocol-grounded non-emergency Air Pollution planner."""

from ecoguard.shared.activity import live_actor
import json

from pydantic import ValidationError

from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import AirPollutionEventAnalysis
from ecoguard.response_planner.air_pollution.schemas import (
    AirPollutionPlanProposal,
    AirPollutionPlanningResult,
    AirPollutionRecommendedAction,
    AirPollutionResponsePlan,
)
from ecoguard.analyzers.emergency.fire.risk_analysis_agent import render_excerpts
from ecoguard.shared.llm import (
    ClaudeLLMService,
    ClaudeProviderError,
    build_system_blocks,
)
from ecoguard.shared.protocols import (
    ProtocolRetriever,
    normalize_for_match,
    verify_citations,
)

SYSTEM_PROMPT = """\
You are EcoGuard's NON-EMERGENCY air-pollution response-planning component.
Produce decision-support recommendations, not operational commands, using only
the supplied Analyzer report and verified air-pollution guidance excerpts.

Strict rules:
- Do not classify an emergency, allocate or dispatch police, ambulances, fire
  services, facilities, personnel, or equipment.
- Do not re-run anomaly detection, p95 comparison, wind selection, transport,
  corridor, population, trend, severity, exposure, or health-risk analysis.
- Unknown severity, trend, and population remain unknown. Do not manufacture
  population or affected-person counts.
- Nearby places and transport screening are context only and do not prove
  exposure, pollutant transport, source, availability, or affected area.
- Every action must copy a reviewed action's recommendation, authority,
  resource, timeframe, and priority exactly.
- Every action must cite supplied protocol chunks. Analysis evidence IDs may be
  referenced only when present in the supplied list.
- Every protocol citation must quote the supplied chunk verbatim.
- Preserve Analyzer limitations and evidence gaps.
"""


class AirPollutionResponsePlanner:
    """Plan from an Analyzer report without routing, persistence, or execution."""

    def __init__(self, *, llm_service=None, retriever=None, top_k: int = 5):
        self.llm_service = llm_service if llm_service is not None else ClaudeLLMService()
        self.retriever = (
            retriever
            if retriever is not None
            else ProtocolRetriever(hazard="air_pollution")
        )
        self.top_k = top_k

    @live_actor("planner.advisory")
    def plan_response(
        self, analysis: AirPollutionEventAnalysis
    ) -> AirPollutionPlanningResult:
        validated = AirPollutionEventAnalysis.model_validate(
            analysis.model_dump(round_trip=True)
        )
        limitations = self._analysis_limitations(validated)
        pollutants = self._pollutants(validated)
        if not pollutants:
            return self._result(
                validated, "skipped", "insufficient_analysis_evidence", limitations
            )
        if getattr(self.retriever, "hazard", None) != "air_pollution":
            return self._result(
                validated, "failed", "guidance_scope_mismatch", limitations
            )

        try:
            documents = getattr(self.retriever, "documents", {})
            # Retrieve wide on purpose. BM25 here is local, in-memory and
            # free, and the pollutant filter below discards most of what it
            # ranks — the chunk carrying the only reviewed action for O3 or NO2
            # sits below rank 15, so any fixed ceiling silently loses those
            # pollutants their plan. What costs money is what gets *sent*, and
            # that is narrowed after the reviewed actions are known.
            retrieval_limit = max(
                self.top_k,
                len(getattr(self.retriever, "chunks", [])),
                len(documents),
            )
            chunks = self.retriever.retrieve(
                self._query(validated, pollutants), top_k=retrieval_limit
            )
            chunks = [
                chunk
                for chunk in chunks
                if pollutants.issubset(
                    set(
                        documents.get(chunk["document_id"], {}).get(
                            "supported_pollutants", []
                        )
                    )
                )
            ]
            reviewed = self._reviewed_actions(chunks, documents)
            # Send only the chunks that can actually ground an action.
            #
            # _actions_grounded requires every action to copy a reviewed action
            # exactly AND to cite a chunk quoting it, so a chunk carrying no
            # reviewed action cannot contribute to an accepted plan — it can
            # only be cited wrongly, which fails the whole plan. Four of the ten
            # corpus documents have no reviewed actions at all; sending their
            # chunks was paying input tokens for text the grounding check was
            # always going to reject.
            #
            # This is a narrowing, not a truncation: the ranked order is kept
            # and top_k still bounds it, but the cut is made on what the
            # verifier needs rather than on rank alone — trimming by rank could
            # drop the single actionable chunk and fail the plan outright.
            grounding_ids = {
                chunk_id
                for action in reviewed
                for chunk_id in action["supporting_chunk_ids"]
            }
            chunks = [
                chunk for chunk in chunks if chunk["chunk_id"] in grounding_ids
            ][: self.top_k]
            reviewed = [
                action for action in reviewed
                if set(action["supporting_chunk_ids"]).issubset(
                    {chunk["chunk_id"] for chunk in chunks}
                )
            ]
            if not reviewed:
                chunks = []
        except Exception:
            chunks = []
            reviewed = []
        if not chunks:
            return self._result(
                validated, "failed", "guidance_unavailable", limitations
            )
        if not getattr(self.llm_service, "available", False):
            return self._result(validated, "failed", "model_unavailable", limitations)

        analysis_evidence_ids = self._analysis_evidence_ids(validated)
        try:
            proposal = self.llm_service.parse_structured(
                system_blocks=build_system_blocks(SYSTEM_PROMPT),
                user_text=self._prompt(
                    validated, chunks, reviewed, analysis_evidence_ids
                ),
                output_format=AirPollutionPlanProposal,
            )
        except ClaudeProviderError:
            return self._result(validated, "failed", "model_failure", limitations)
        try:
            proposal = AirPollutionPlanProposal.model_validate(
                proposal.model_dump()
                if isinstance(proposal, AirPollutionPlanProposal)
                else proposal
            )
        except (ValidationError, TypeError, AttributeError):
            return self._result(validated, "failed", "malformed_output", limitations)

        payload = proposal.model_dump(mode="json")
        citations, dropped = verify_citations(payload["protocol_citations"], chunks)
        verified_chunk_ids = {citation["chunk_id"] for citation in citations}
        action_chunk_ids = {
            chunk_id
            for action in proposal.actions
            for chunk_id in action.supporting_chunk_ids
        }
        action_analysis_ids = {
            evidence_id
            for action in proposal.actions
            for evidence_id in action.supporting_analysis_evidence_ids
        }
        if (
            dropped
            or not citations
            or not action_chunk_ids.issubset(verified_chunk_ids)
            or not action_analysis_ids.issubset(analysis_evidence_ids)
            or not self._actions_grounded(proposal, reviewed, citations)
        ):
            return self._result(
                validated, "failed", "ungrounded_response", limitations
            )

        spatial_relevance = (
            "Existing transport/corridor output is contextual screening only; "
            "it does not confirm exposure or change this protocol recommendation."
            if validated.transport_analysis.result is not None
            else None
        )
        verified_actions = [
            AirPollutionRecommendedAction(
                **action.model_dump(
                    exclude={"rationale", "spatial_relevance"}
                ),
                rationale=(
                    "This recommendation exactly matches a reviewed action and "
                    "its verified protocol passage."
                ),
                spatial_relevance=spatial_relevance,
            )
            for action in proposal.actions
        ]
        plan = AirPollutionResponsePlan(
            status="success",
            summary=" ".join(action.recommendation for action in verified_actions),
            recommended_authority_types=proposal.recommended_authority_types,
            recommended_resource_types=proposal.recommended_resource_types,
            actions=verified_actions,
            assumptions=[],
            evidence_gaps=self._unavailable_evidence_gaps(validated),
            limitations=limitations,
            analysis_evidence_references=sorted(action_analysis_ids),
            protocol_references=citations,
        )
        return AirPollutionPlanningResult(analysis=validated, plan=plan)

    @staticmethod
    def _pollutants(analysis: AirPollutionEventAnalysis) -> set[str]:
        state = analysis.current_state.result
        return (
            {candidate.anomaly.pollutant for candidate in state.detections}
            if state is not None
            else set()
        )

    @staticmethod
    def _query(
        analysis: AirPollutionEventAnalysis, pollutants: set[str]
    ) -> str:
        unavailable = [
            name
            for name, component in (
                ("severity", analysis.severity_assessment),
                ("trend", analysis.future_prediction),
                ("population", analysis.population_impact),
            )
            if component.status == "unavailable"
        ]
        return (
            f"non emergency air pollution {' '.join(sorted(pollutants))} "
            f"monitoring public information advisory unavailable {' '.join(unavailable)}"
        )

    # Detector internals that belong in the incident record and never in a
    # prompt. One air-pollution signal carries about 43 KB of these — a full
    # detection_result and correlation_candidate — and an incident accumulates
    # one per reading across its 18-hour life. Serialising the analysis whole
    # therefore grew the prompt with the incident's age: a single observed call
    # sent 254,405 input tokens, and twelve calls cost $2.76 in four minutes.
    #
    # The planner needs none of it. It may only copy reviewed actions and cite
    # supplied excerpts, and the evidence IDs it is allowed to reference are
    # passed separately, so dropping these changes nothing it is permitted to
    # do.
    PROMPT_EXCLUDED_KEYS = frozenset({
        "detection_result",
        "correlation_candidate",
        "baseline_evidence",
        "raw_payload",
        "signals",
    })

    @classmethod
    def _compact(cls, value, depth: int = 0):
        """The analysis with the bulky detector internals stripped out."""
        if depth > 12:
            return "..."
        if isinstance(value, dict):
            return {
                key: cls._compact(item, depth + 1)
                for key, item in value.items()
                if key not in cls.PROMPT_EXCLUDED_KEYS
            }
        if isinstance(value, list):
            # A long list here is repeated readings, not distinct facts. The
            # count is kept so the model is not misled into thinking it saw
            # everything.
            if len(value) > 20:
                return [
                    *(cls._compact(item, depth + 1) for item in value[:20]),
                    f"... {len(value) - 20} more omitted",
                ]
            return [cls._compact(item, depth + 1) for item in value]
        return value

    @classmethod
    def _prompt(cls, analysis, chunks, reviewed, evidence_ids):
        report = cls._compact(analysis.model_dump(mode="json"))
        return (
            "# Non-emergency Air Pollution Analyzer report\n"
            f"{json.dumps(report, ensure_ascii=False, indent=2)}\n\n"
            "# Available analysis evidence IDs\n"
            f"{json.dumps(sorted(evidence_ids), ensure_ascii=False)}\n\n"
            "# Verified pollution-guidance excerpts\n"
            f"{render_excerpts(chunks)}\n\n"
            "# Reviewed actions (exact action fields required)\n"
            f"{json.dumps(reviewed, ensure_ascii=False)}\n\n"
            "# Task\nReturn only grounded non-emergency recommendations."
        )

    @staticmethod
    def _reviewed_actions(chunks, documents):
        reviewed = []
        for chunk in chunks:
            for action in documents[chunk["document_id"]].get("reviewed_actions", []):
                if normalize_for_match(action["recommendation"]) in normalize_for_match(
                    chunk["text"]
                ):
                    reviewed.append(
                        {**action, "supporting_chunk_ids": [chunk["chunk_id"]]}
                    )
        return reviewed

    @staticmethod
    def _actions_grounded(proposal, reviewed, citations):
        fields = (
            "recommendation",
            "responsible_authority_type",
            "resource_type",
            "timeframe",
            "priority",
        )
        for action in proposal.actions:
            if not any(
                all(getattr(action, field) == approved[field] for field in fields)
                and set(action.supporting_chunk_ids).issubset(
                    approved["supporting_chunk_ids"]
                )
                for approved in reviewed
            ):
                return False
            if not any(
                citation["chunk_id"] in action.supporting_chunk_ids
                and normalize_for_match(action.recommendation)
                in normalize_for_match(citation["quoted_text"])
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
    def _analysis_evidence_ids(analysis: AirPollutionEventAnalysis) -> set[str]:
        identifiers = {item.evidence_id for item in analysis.evidence}
        identifiers.update(
            item.evidence_id for item in analysis.transport_analysis.evidence
        )
        identifiers.update(
            item.evidence_id for item in analysis.future_prediction.evidence
        )
        state = analysis.current_state.result
        if state is not None:
            for candidate in state.detections:
                identifiers.update(value for _, value in candidate.evidence_references)
        return identifiers

    @staticmethod
    def _analysis_limitations(analysis: AirPollutionEventAnalysis) -> list[str]:
        limitations = [
            "Non-emergency decision support only; no allocation, dispatch, or implementation is represented.",
            *analysis.limitations,
        ]
        for label, component in (
            ("Event-level severity", analysis.severity_assessment),
            ("Future trend", analysis.future_prediction),
            ("Population impact", analysis.population_impact),
        ):
            if component.status == "unavailable":
                limitations.append(
                    f"{label} is unavailable: {component.unavailable_reason}."
                )
        if analysis.transport_analysis.status == "unavailable":
            limitations.append(
                "Transport/spatial analysis is unavailable; no affected area is inferred."
            )
        else:
            limitations.extend(analysis.transport_analysis.limitations)
        return list(dict.fromkeys(limitations))

    @staticmethod
    def _unavailable_evidence_gaps(
        analysis: AirPollutionEventAnalysis,
    ) -> list[str]:
        return [
            f"{label} unavailable: {component.unavailable_reason}."
            for label, component in (
                ("Event-level severity", analysis.severity_assessment),
                ("Future trend", analysis.future_prediction),
                ("Population impact", analysis.population_impact),
            )
            if component.status == "unavailable"
        ]

    @staticmethod
    def _result(analysis, status, reason, limitations):
        return AirPollutionPlanningResult(
            analysis=analysis,
            plan=AirPollutionResponsePlan(
                status=status,
                reason=reason,
                limitations=limitations,
            ),
        )
