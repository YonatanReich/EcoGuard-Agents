"""
Response Planning Agent

Responsible for turning an assessed fire event into a concrete, protocol-grounded
response plan: which emergency units to activate, and what each should do by when.

Why this is a separate agent and a second model call:
    A single call producing both the risk score and the plan would be cheaper.
    It retrieves worse, though, and that is the deciding factor. The risk agent
    queries the corpus for classification and danger-rating language; this agent
    queries the same corpus for action, mobilisation and evacuation language.
    One blended query returns a compromise that serves neither well, and
    "retrieve and cite protocol content" for both halves is the substance of
    this sprint rather than an architectural nicety.

    It also matches how the repo already reasons. FireDetectionAgent explicitly
    refuses to compute a risk score, keeping detection, satellite confidence and
    fire-weather severity distinct. Risk and response plan are distinct in the
    same way. And separating them means a planning failure still leaves a usable
    risk score on the map rather than losing both.

The hard gate:
    plan_response refuses to run unless the risk assessment succeeded. Producing
    a response plan for a risk we could not determine would be fabrication of
    the worst kind — an operator could act on it. It also means no model call is
    made for the no-event scans that make up most requests.

Consumed by: ecoguard.api.main.get_detected_events
"""

from __future__ import annotations

from datetime import datetime, timezone

from ecoguard.analyzers.fire.risk_analysis_agent import (
    build_event_id,
    build_evidence_summary,
    render_excerpts,
    section,
)
from ecoguard.shared.llm import (
    ClaudeLLMService,
    build_system_blocks,
)
from ecoguard.shared.protocols import ProtocolRetriever
from ecoguard.planners.shared.adapters import (
    OperationalAnalysisUnavailable,
    build_fire_plan_input,
)
from ecoguard.planners.shared.planner import EmergencyResponsePlanner
from ecoguard.planners.shared.schemas import EmergencyPlanProposal

AGENT_NAME = "ResponsePlanningAgent"

DEFAULT_TOP_K = 5

PLANNING_SYSTEM_PROMPT = """\
You are the response planning component of EcoGuard Agents, a multi-agent system
for environmental crisis management in Israel. A wildfire has been detected and
already assessed for operational risk. Your job is to turn that assessment into a
concrete response plan, grounded in the fire-protocol excerpts supplied with each
request.

## What you are given

- The detected event and its evidence: location, satellite detection, fire
  weather, current conditions, and what lies nearby.
- A completed risk assessment: a score from 0 to 100, a derived risk band, the
  drivers behind it, and the gaps in the evidence.
- Protocol excerpts retrieved for this specific situation.

Treat the risk assessment as authoritative. Do not re-score the event, do not
argue with the score, and do not contradict it. Plan a response proportionate to
it.

## The units you may recommend

Use only these identifiers:

- fire_department — ground suppression, structure protection.
- police — access control, road closures, evacuation enforcement.
- medical_services — casualty treatment, triage, medical evacuation.
- municipal_emergency_team — local coordination, shelters, public information.
- home_front_command — large-scale evacuation and civil protection.
- aerial_firefighting — water and retardant drops.
- forestry_service — wildland fire expertise, fuel and terrain knowledge.
- utility_operator — power line de-energisation and utility isolation.

Every unit you assign an action to must also appear in recommended_units. A plan
that gives work to a unit nobody dispatched leaves an operator with a task and no
responder, and will be rejected.

## Writing actions

Each action needs a specific instruction, one responsible unit, and a timeframe
of immediate, within_1_hour, within_6_hours, or ongoing.

- Order actions by operational priority. Position in the list is the order;
  there is no separate index field.
- Be concrete. "Close Route 443 at the eastern junction and stage traffic
  control" is actionable; "manage traffic" is not.
- Scale to the assessed risk. A medium-risk event warrants verification and
  monitoring, not a full mobilisation. A critical event warrants immediate
  life-safety measures.
- Ground the plan in what is actually nearby. Do not assign structure protection
  where no structures were found, and do not assume resources the evidence does
  not show. If no fire station is nearby, extended response time is a planning
  constraint you should name.
- Firefighter safety governs engagement. Where the protocols make an action
  conditional on escape routes, safety zones or communications, say so in the
  action rather than assuming those conditions hold.

Put anything your plan takes for granted into assumptions — resource
availability, road passability, that the detection reflects an active fire — so
an operator can check them before acting.

## Grounding rules — these are strict

The user message contains protocol excerpts, each preceded by a marker of the
form [chunk_id: some-id]. These excerpts are the only source you may cite.

1. Every citation's chunk_id must be copied character-for-character from a
   [chunk_id: ...] marker in this request. Never construct, guess or adapt an id.
2. Every quoted_text must be a verbatim span copied from the body of that same
   chunk. Do not paraphrase and do not join text from two chunks.
3. Each action's `supporting_protocol_chunk_ids` must contain only the supplied
   chunk ids that directly support that specific action. Never copy all plan
   citations onto every action.
4. Cite at least one passage and at most six. Each citation's `supports` field
   must state which part of the plan that passage backs up.
5. Where the excerpts do not cover something your plan depends on, put it in
   assumptions. Do not cite from memory or dress up general knowledge as
   protocol guidance.

Citations are verified programmatically against the excerpts you were given. A
plan left with no surviving citation is rejected in full.

## Style

Write for an emergency operations officer who will act on this within minutes.
Lead with what protects life. Be brief and specific.
"""


class ResponsePlanningAgent:
    """
    Produces a protocol-grounded response plan for an assessed fire event.

    Attributes:
        llm_service: Anything exposing ``available`` and ``parse_structured``.
        retriever: Anything exposing ``retrieve(query, top_k) -> list[dict]``.
        top_k (int): Number of protocol chunks to retrieve per plan.
    """

    def __init__(
        self,
        *,
        llm_service: object | None = None,
        retriever: object | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self.llm_service = llm_service if llm_service is not None else ClaudeLLMService()
        self.retriever = retriever if retriever is not None else ProtocolRetriever()
        self.top_k = top_k
        self.shared_planner = EmergencyResponsePlanner(
            llm_service=self.llm_service,
            retriever=self.retriever,
            # Legacy injected test retrievers predate hazard metadata. Binding
            # them here is explicit and cannot accidentally authorize Flood.
            retriever_hazard="fire",
            top_k=top_k,
            query_builder=self._shared_query,
            prompt_builder=self._shared_prompt,
            proposal_model=EmergencyPlanProposal,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def plan_response(self, detected_event: dict, risk_assessment: dict) -> dict:
        """
        Plan the response to an assessed fire event.

        Args:
            detected_event (dict): The FireDetectionAgent result.
            risk_assessment (dict): The RiskAnalysisAgent result.

        Returns:
            dict: A response plan. metadata.planning_status is "success",
                "failed" or "skipped". Every non-success path returns empty
                units and actions rather than a generic fallback plan.
        """
        if not isinstance(risk_assessment, dict):
            return self.build_skipped_plan("risk_analysis_unavailable", detected_event)

        try:
            analysis = build_fire_plan_input(detected_event, risk_assessment)
        except OperationalAnalysisUnavailable:
            return self.build_skipped_plan("risk_analysis_unavailable", detected_event)

        result = self.shared_planner.plan_response(analysis).model_dump(mode="json")
        return self._legacy_wire_result(result)

    def _shared_query(self, analysis) -> str:
        context = analysis.additional_context
        legacy_terms = self.build_query(
            context["detected_event"], context["risk_assessment"]
        )
        return f"{analysis.event_description} {legacy_terms}"

    def _shared_prompt(self, analysis, chunks):
        context = analysis.additional_context
        system_blocks, legacy_prompt = self.build_prompt(
            context["detected_event"], context["risk_assessment"], chunks
        )
        user_text = (
            "# Analyzer event description\n\n"
            f"{analysis.event_description}\n\n"
            f"{legacy_prompt}"
        )
        return system_blocks, user_text

    @staticmethod
    def _legacy_wire_result(result: dict) -> dict:
        """Add the established Fire aliases and legacy error vocabulary."""
        error_map = {
            "missing_credentials": "missing credentials",
            "protocol_corpus_unavailable": "protocol corpus unavailable",
            "no_protocol_match": "no protocol match",
            "protocol_retrieval_failed": "protocol corpus unavailable",
            "protocol_hazard_mismatch": "protocol corpus unavailable",
            "ungrounded_response": "ungrounded response",
            "malformed_response": "malformed response",
        }
        result["event_id"] = result.get("incident_id")
        result["event_type"] = result.get("hazard_type", "fire")
        result["metadata"]["agent"] = AGENT_NAME
        if result.get("error") in error_map:
            result["error"] = error_map[result["error"]]
        return result

    # ------------------------------------------------------------------
    # Query construction
    # ------------------------------------------------------------------

    def build_query(self, detected_event: dict, risk_assessment: dict) -> str:
        """
        Build the retrieval query for action-oriented protocol content.

        Deliberately different from the risk agent's query: this one reaches for
        mobilisation, evacuation and structure-protection language rather than
        danger classification. Running two targeted queries against one corpus is
        the main reason this is a separate call.

        Args:
            detected_event (dict): The detected event.
            risk_assessment (dict): The completed risk assessment.

        Returns:
            str: A bag of terms for BM25.
        """
        terms = [
            "initial attack response actions resource allocation",
            "incident command evacuation public warning structure protection",
        ]

        level = risk_assessment.get("risk_level")
        if level:
            terms.append(f"{level} risk response")
        if level in {"high", "critical"}:
            terms.append("write off structures scarce resources hard decisions defend")

        # Area type steers the second retrieval toward the right half of the
        # corpus: a fire in a building needs the offensive/defensive doctrine,
        # a fire in the open needs containment and triage.
        situational = self._section(risk_assessment, "situational_context")
        area_type = situational.get("area_type")

        if area_type in {"urban_dense", "urban_residential", "industrial"}:
            terms.append(
                "structure fire offensive defensive interior operations occupants "
                "building acceptable risk"
            )
        elif area_type == "wildland_urban_interface":
            terms.append("wildland urban interface structure triage defensible space")
        elif area_type in {"open_natural", "agricultural"}:
            terms.append("open natural fuels containment flank anchor point")

        if situational.get("evacuation_consideration") in {
            "localised_evacuation",
            "large_scale_evacuation",
        }:
            terms.append("evacuation public warning relocation sheltering")

        geospatial = self._section(detected_event, "geospatial_context")

        if geospatial.get("nearby_settlements"):
            terms.append(
                "evacuation warning structure triage defensible space sheltering residents"
            )
        if geospatial.get("nearby_hospitals"):
            terms.append("medical evacuation casualty triage special needs populations")
        if geospatial.get("nearby_roads"):
            terms.append("road closure access route egress driveway safety zone")
        if not geospatial.get("nearby_fire_stations"):
            terms.append("mutual aid extended response time remote access")

        # Carry the first call's reasoning into the second retrieval so the plan
        # is fetched against the drivers that actually produced the score.
        drivers = risk_assessment.get("primary_drivers") or []
        terms.extend(str(driver) for driver in drivers[:6])

        return " ".join(terms)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def build_prompt(
        self, detected_event: dict, risk_assessment: dict, chunks: list[dict]
    ) -> tuple[list[dict], str]:
        """
        Build the system blocks and user message for the planning call.

        Args:
            detected_event (dict): The detected event.
            risk_assessment (dict): The completed risk assessment.
            chunks (list[dict]): Retrieved protocol chunks.

        Returns:
            tuple[list[dict], str]: System blocks and user text.
        """
        # Shared renderer, so the model is told the same story about the
        # evidence in both calls rather than reading two drifting summaries.
        evidence = build_evidence_summary(detected_event)
        assessment_summary = self.build_assessment_summary(risk_assessment)
        excerpts = render_excerpts(chunks)

        user_text = (
            "# Detected fire event\n\n"
            f"{evidence}\n\n"
            "# Risk assessment (authoritative — do not re-score)\n\n"
            f"{assessment_summary}\n\n"
            "# Protocol excerpts\n\n"
            "These are the only passages you may cite. Copy chunk ids exactly.\n\n"
            f"{excerpts}\n\n"
            "# Task\n\n"
            "Produce a response plan proportionate to the assessed risk. Cite the "
            "excerpts that justify your actions, and record what the plan takes "
            "for granted in assumptions."
        )

        return build_system_blocks(PLANNING_SYSTEM_PROMPT), user_text

    def build_assessment_summary(self, risk_assessment: dict) -> str:
        """
        Render the risk assessment as authoritative planning input.

        Includes the verified citations from the risk call so the planner can see
        which protocol passages already justified the score, and evidence gaps so
        it does not plan around information nobody has.

        Args:
            risk_assessment (dict): The completed risk assessment.

        Returns:
            str: Markdown summary.
        """
        lines = [
            f"- Risk score: {risk_assessment.get('risk_score')} / 100",
            f"- Risk level: {risk_assessment.get('risk_level')}",
            f"- Assessment confidence: {risk_assessment.get('confidence')}",
        ]

        # Absent on an assessment produced before this field existed, so read it
        # defensively rather than assuming it is there.
        situational = self._section(risk_assessment, "situational_context")
        if situational:
            lines.append("- Situational context:")
            lines.append(f"  - Area type: {situational.get('area_type')}")
            if situational.get("area_type_basis"):
                lines.append(f"    ({situational['area_type_basis']})")
            lines.append(
                f"  - Population nearby: {situational.get('population_band')} "
                f"(basis: {situational.get('population_basis')})"
            )
            lines.append(
                f"  - Evacuation consideration: "
                f"{situational.get('evacuation_consideration')}"
            )
            for gap in situational.get("context_gaps") or []:
                lines.append(f"  - Context gap: {gap}")

        # Facts looked up rather than collected. Flagged separately so the
        # planner can weigh them accordingly.
        findings = risk_assessment.get("web_findings") or []
        if findings:
            lines.append("- Facts looked up externally (weaker than collected data):")
            for finding in findings:
                lines.append(
                    f"  - {finding.get('fact')} [{finding.get('source_title')}]"
                )

        drivers = risk_assessment.get("primary_drivers") or []
        if drivers:
            lines.append("- Primary drivers:")
            lines.extend(f"  - {driver}" for driver in drivers)

        explanation = risk_assessment.get("explanation")
        if explanation:
            lines.append(f"- Assessment rationale: {explanation}")

        gaps = risk_assessment.get("evidence_gaps") or []
        if gaps:
            lines.append("- Evidence gaps identified during assessment:")
            lines.extend(f"  - {gap}" for gap in gaps)

        citations = self._section(risk_assessment, "grounding").get("citations") or []
        if citations:
            lines.append("- Protocol passages already cited for the risk score:")
            for citation in citations:
                lines.append(
                    f"  - [{citation.get('chunk_id')}] {citation.get('supports')}"
                )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Response builders
    # ------------------------------------------------------------------

    def build_response_plan(
        self,
        *,
        payload: dict,
        detected_event: dict,
        risk_assessment: dict,
        chunks: list[dict],
        citations: list[dict],
        dropped: int,
    ) -> dict:
        """
        Build a successful plan from a validated model response.

        The agent emits the rich ``response_actions`` form only. Flattening to a
        plain list of strings for the dashboard is done by ecoguard.api.main, which
        owns transport concerns.

        Args:
            payload (dict): Validated proposal model output.
            detected_event (dict): The event planned for, used for identity.
            risk_assessment (dict): The assessment this plan answers.
            chunks (list[dict]): Chunks that were retrieved.
            citations (list[dict]): Citations that survived verification.
            dropped (int): Citations that failed verification.

        Returns:
            dict: The unified response plan.
        """
        return {
            "metadata": {
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "planning_status": "success",
                "model": getattr(self.llm_service, "model", None),
                "reason": None,
            },
            # Identity, so this plan is meaningful on its own. A resource
            # allocation agent receiving only the plan must be able to tell
            # which fire it is for and how severe that fire was judged to be;
            # correlating by "arrived in the same HTTP response" is not a
            # contract.
            "event_id": build_event_id(detected_event),
            "event_type": detected_event.get("event_type", "fire"),
            "location": section(detected_event, "location"),
            "responding_to": {
                "risk_score": risk_assessment.get("risk_score"),
                "risk_level": risk_assessment.get("risk_level"),
                "risk_semantics": risk_assessment.get("risk_semantics"),
            },
            "recommended_units": payload["recommended_units"],
            "response_actions": payload["actions"],
            "plan_summary": payload["plan_summary"],
            "assumptions": payload["assumptions"],
            "grounding": {
                "retriever": "bm25",
                "retrieved_chunk_ids": [chunk["chunk_id"] for chunk in chunks],
                "citations": citations,
                "unverified_citation_count": dropped,
            },
            "error": None,
        }

    def build_skipped_plan(self, reason: str, detected_event: dict | None = None) -> dict:
        """
        Build a plan for an event that was never a planning candidate.

        Args:
            reason (str): "risk_analysis_unavailable" or
                "analysis_not_requested".
            detected_event (dict | None): The event, when known, so the empty
                plan still carries the identity of what it declined to plan for.

        Returns:
            dict: A skipped plan with no units and no actions.
        """
        return self._build_empty(
            status="skipped", reason=reason, error=None, detected_event=detected_event
        )

    def build_failed_plan(self, error: str, detected_event: dict | None = None) -> dict:
        """
        Build a plan for an event we tried and failed to plan for.

        Args:
            error (str): A category from the closed error vocabulary, or
                "ungrounded response" / "no protocol match" /
                "protocol corpus unavailable".
            detected_event (dict | None): The event, when known.

        Returns:
            dict: A failed plan with no units and no actions.
        """
        return self._build_empty(
            status="failed", reason=None, error=error, detected_event=detected_event
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_empty(
        self,
        *,
        status: str,
        reason: str | None,
        error: str | None,
        detected_event: dict | None = None,
    ) -> dict:
        """
        Shared shape for skipped and failed plans.

        Empty lists, never a generic "monitor the area" fallback. A plausible
        default plan is indistinguishable from a real one at the API boundary,
        which is exactly why there isn't one.

        The identity block is still populated when the event is known, so a
        consumer can tell *which* event has no plan rather than receiving an
        anonymous empty object.
        """
        event = detected_event if isinstance(detected_event, dict) else {}

        return {
            "metadata": {
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "planning_status": status,
                "model": None,
                "reason": reason,
            },
            "event_id": build_event_id(event) if event else None,
            "event_type": event.get("event_type", "fire"),
            "location": section(event, "location"),
            "responding_to": {
                "risk_score": None,
                "risk_level": None,
                "risk_semantics": None,
            },
            "recommended_units": [],
            "response_actions": [],
            "plan_summary": None,
            "assumptions": [],
            "grounding": {
                "retriever": "bm25",
                "retrieved_chunk_ids": [],
                "citations": [],
                "unverified_citation_count": 0,
            },
            "error": error,
        }

    @staticmethod
    def _section(source: dict, key: str) -> dict:
        """Read a nested section, tolerating None and wrong types."""
        if not isinstance(source, dict):
            return {}

        value = source.get(key)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _timestamp() -> str:
        """UTC timestamp in the format every other agent in this project uses."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
