"""Hazard-scoped, fail-closed planning for already analyzed emergencies."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable

from pydantic import ValidationError

from ecoguard.response_planner.emergency.schemas import (
    EmergencyLocation,
    EmergencyPlanProposal,
    EmergencyResponsePlan,
    EmergencyResponsePlanInput,
)
from ecoguard.shared.llm import ClaudeLLMService, ClaudeProviderError, build_system_blocks
from ecoguard.shared.protocols import ProtocolRetriever, verify_citations

AGENT_NAME = "EmergencyResponsePlanner"
DEFAULT_TOP_K = 5

EMERGENCY_PLANNING_SYSTEM_PROMPT = """\
You are EcoGuard's emergency response planning component. You receive an
emergency incident that has already been detected and analyzed. Produce
decision-support requirements for unit TYPES and ordered response actions.

Strict boundaries:
- Treat any supplied risk context as authoritative. Never calculate, change,
  reinterpret, or infer severity when it is absent.
- Never detect or correlate incidents; model fire spread, flood propagation or
  inundation; calculate population or exposure; or infer missing facts.
- Never select a station, facility, vehicle, crew, route, resource quantity, or
  claim that dispatch occurred. Never claim availability.
- Preserve unknowns, evidence gaps, limitations, and assumptions.
- Use only facts in the analyzer input and only protocol excerpts supplied in
  this request. Do not use remembered protocol guidance.
- Respect each excerpt's jurisdiction and applicability metadata. Guidance
  marked supplementary or requiring local adaptation must not be presented as
  binding Israeli law, authority, agency responsibility, threshold, or road rule.
- recommended_units contains unit-type identifiers only.
- Order actions by operational priority. Each action names one responsible unit
  type, a timeframe, and one or more supporting_protocol_chunk_ids copied from
  the supplied excerpts.
- Every protocol citation must identify a supplied chunk and quote it verbatim.
"""

QueryBuilder = Callable[[EmergencyResponsePlanInput], str]
PromptBuilder = Callable[
    [EmergencyResponsePlanInput, list[dict]], tuple[list[dict], str]
]


class EmergencyResponsePlanner:
    """Create a grounded plan without performing analysis or allocation."""

    def __init__(
        self,
        *,
        llm_service: object | None = None,
        retriever: object | None = None,
        retriever_hazard: str | None = None,
        top_k: int = DEFAULT_TOP_K,
        query_builder: QueryBuilder | None = None,
        prompt_builder: PromptBuilder | None = None,
        proposal_model: type = EmergencyPlanProposal,
    ) -> None:
        self.llm_service = llm_service if llm_service is not None else ClaudeLLMService()
        self.retriever = retriever
        self.retriever_hazard = retriever_hazard
        self.top_k = top_k
        self.query_builder = query_builder
        self.prompt_builder = prompt_builder
        self.proposal_model = proposal_model

    def plan_response(
        self, analysis: EmergencyResponsePlanInput | dict | None
    ) -> EmergencyResponsePlan:
        """Plan from an explicit hazard and upstream event description."""

        hazard = self._validated_hazard(analysis)
        try:
            validated = EmergencyResponsePlanInput.model_validate(analysis)
        except (ValidationError, TypeError):
            return self._empty_from_raw(
                analysis,
                hazard=hazard,
                status="skipped",
                reason="invalid_planner_input",
            )

        retriever, scope_error = self._scoped_retriever(validated.hazard_type)
        if scope_error is not None:
            return self._empty(
                validated, status="failed", error=scope_error
            )

        if not getattr(retriever, "available", True):
            return self._empty(
                validated, status="failed", error="protocol_corpus_unavailable"
            )

        # Checking corpus readiness is not retrieval. Once doctrine exists,
        # preserve the established Fire behavior: do no retrieval work when a
        # Claude call cannot be attempted.
        if not getattr(self.llm_service, "available", False):
            return self._empty(validated, status="failed", error="missing_credentials")

        query = (
            self.query_builder(validated)
            if self.query_builder is not None
            else self.build_query(validated)
        )
        try:
            chunks = retriever.retrieve(query, top_k=self.top_k)
        except Exception:
            return self._empty(
                validated, status="failed", error="protocol_retrieval_failed"
            )
        if not chunks:
            return self._empty(validated, status="failed", error="no_protocol_match")

        system_blocks, user_text = (
            self.prompt_builder(validated, chunks)
            if self.prompt_builder is not None
            else self.build_prompt(validated, chunks)
        )
        try:
            raw_proposal = self.llm_service.parse_structured(
                system_blocks=system_blocks,
                user_text=user_text,
                output_format=self.proposal_model,
            )
            payload = (
                raw_proposal.model_dump(mode="json")
                if hasattr(raw_proposal, "model_dump")
                else raw_proposal
            )
            payload = EmergencyPlanProposal.model_validate(payload).model_dump(
                mode="json"
            )
        except ClaudeProviderError as error:
            return self._empty(validated, status="failed", error=str(error))
        except (ValidationError, TypeError, AttributeError):
            return self._empty(validated, status="failed", error="malformed_response")

        citations, dropped = verify_citations(
            payload.get("protocol_citations") or [], chunks
        )
        # A partially fabricated citation set is still an ungrounded response;
        # silently retaining its valid half hides that the model invented evidence.
        if dropped or not citations:
            return self._empty(
                validated,
                status="failed",
                error="ungrounded_response",
                unverified_citation_count=dropped,
            )

        verified_ids = {citation["chunk_id"] for citation in citations}
        actions = []
        for raw_action in payload.get("actions") or []:
            action = dict(raw_action)
            supporting = action.get("supporting_protocol_chunk_ids")
            if not supporting or not set(supporting).issubset(verified_ids):
                return self._empty(
                    validated, status="failed", error="ungrounded_response"
                )
            actions.append(action)

        return EmergencyResponsePlan(
            metadata={
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "planning_status": "success",
                "model": getattr(self.llm_service, "model", None),
                "reason": None,
            },
            incident_id=validated.incident_id,
            hazard_type=validated.hazard_type,
            location=validated.location,
            responding_to=validated.risk_context,
            plan_summary=payload["plan_summary"],
            recommended_units=payload["recommended_units"],
            response_actions=actions,
            assumptions=payload.get("assumptions") or [],
            evidence_gaps=validated.evidence_gaps,
            limitations=validated.limitations,
            grounding={
                "retriever": "bm25",
                "retrieved_chunk_ids": [chunk["chunk_id"] for chunk in chunks],
                "citations": citations,
                "unverified_citation_count": dropped,
            },
            error=None,
        )

    def _scoped_retriever(self, hazard: str) -> tuple[object, str | None]:
        if self.retriever is None:
            return ProtocolRetriever(hazard=hazard), None

        declared = getattr(self.retriever, "hazard", None)
        bound = self.retriever_hazard
        if declared is not None and bound is not None and declared != bound:
            return self.retriever, "protocol_hazard_mismatch"
        effective = declared if declared is not None else bound
        if effective != hazard:
            return self.retriever, "protocol_hazard_mismatch"
        return self.retriever, None

    @staticmethod
    def _validated_hazard(analysis: object) -> str:
        if isinstance(analysis, EmergencyResponsePlanInput):
            return analysis.hazard_type
        if isinstance(analysis, dict):
            hazard = analysis.get("hazard_type")
            if hazard not in {"fire", "flood"}:
                raise ValueError("unsupported emergency hazard")
            return str(hazard)
        # There is no safe doctrine to select without a hazard.
        raise ValueError("emergency hazard is required")

    @staticmethod
    def build_query(analysis: EmergencyResponsePlanInput) -> str:
        return " ".join(
            [
                analysis.hazard_type,
                "emergency response incident command life safety",
                "unit types ordered actions",
                analysis.event_description,
            ]
        )

    @staticmethod
    def build_prompt(
        analysis: EmergencyResponsePlanInput, chunks: list[dict]
    ) -> tuple[list[dict], str]:
        excerpts = "\n\n".join(
            EmergencyResponsePlanner._render_chunk(chunk) for chunk in chunks
        )
        user_text = (
            "# Already analyzed emergency input\n\n"
            f"{json.dumps(analysis.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n\n"
            "# Hazard-scoped protocol excerpts\n\n"
            "These are the only protocol passages you may cite.\n\n"
            f"{excerpts}\n\n"
            "# Task\n\n"
            "Produce unit-type requirements and ordered actions. Preserve supplied "
            "context, gaps, and limitations; do not perform analysis or allocation."
        )
        return build_system_blocks(EMERGENCY_PLANNING_SYSTEM_PROMPT), user_text

    @staticmethod
    def _render_chunk(chunk: dict) -> str:
        """Render trusted provenance so jurisdiction is visible to Claude."""
        metadata = [f"Title: {chunk.get('document_title') or chunk['document_id']}"]
        for label, key in (
            ("Publisher", "publisher"),
            ("Jurisdiction", "jurisdiction"),
            ("Applicability", "applicability"),
        ):
            if chunk.get(key):
                metadata.append(f"{label}: {chunk[key]}")
        if chunk.get("local_adaptation_required") is not None:
            value = "true" if chunk["local_adaptation_required"] else "false"
            metadata.append(f"Local adaptation required: {value}")
        return (
            f"[chunk_id: {chunk['chunk_id']}]\n"
            + "\n".join(metadata)
            + f"\n\n{chunk['text']}"
        )

    def _empty(
        self,
        analysis: EmergencyResponsePlanInput,
        *,
        status: str,
        reason: str | None = None,
        error: str | None = None,
        unverified_citation_count: int = 0,
    ) -> EmergencyResponsePlan:
        return EmergencyResponsePlan(
            metadata={
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "planning_status": status,
                "model": None,
                "reason": reason,
            },
            incident_id=analysis.incident_id,
            hazard_type=analysis.hazard_type,
            location=analysis.location,
            responding_to=analysis.risk_context,
            recommended_units=[],
            response_actions=[],
            plan_summary=None,
            assumptions=[],
            evidence_gaps=analysis.evidence_gaps,
            limitations=analysis.limitations,
            grounding={"unverified_citation_count": unverified_citation_count},
            error=error,
        )

    def _empty_from_raw(
        self,
        raw: object,
        *,
        hazard: str,
        status: str,
        reason: str,
    ) -> EmergencyResponsePlan:
        source = raw if isinstance(raw, dict) else {}
        try:
            location = EmergencyLocation.model_validate(source.get("location"))
        except (ValidationError, TypeError):
            location = None
        gaps = source.get("evidence_gaps")
        limitations = source.get("limitations")
        return EmergencyResponsePlan(
            metadata={
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "planning_status": status,
                "model": None,
                "reason": reason,
            },
            incident_id=(str(source["incident_id"]) if source.get("incident_id") else None),
            hazard_type=hazard,
            location=location,
            responding_to=(
                source.get("risk_context")
                if isinstance(source.get("risk_context"), dict)
                else None
            ),
            recommended_units=[],
            response_actions=[],
            plan_summary=None,
            assumptions=[],
            evidence_gaps=(
                [str(item) for item in gaps] if isinstance(gaps, list) else []
            ),
            limitations=(
                [str(item) for item in limitations]
                if isinstance(limitations, list)
                else []
            ),
            grounding={},
            error=None,
        )

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "AGENT_NAME",
    "EMERGENCY_PLANNING_SYSTEM_PROMPT",
    "EmergencyResponsePlanner",
]
