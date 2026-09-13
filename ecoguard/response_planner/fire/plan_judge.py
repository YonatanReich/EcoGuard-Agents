"""
Response Plan Judge Agent

Responsible for grading a response plan against the protocol corpus and saying
where the pipeline is weak.

There is no reference answer. The judge holds the same hazard-indexed protocol
filebase the planner does, retrieves against it independently, and decides
whether the plan makes operational sense given what the protocols say. It is
explicitly instructed that two plans differing in wording but agreeing in
substance must score identically — the thing being measured is judgement, not
phrasing.

Independence, and why it is mechanical rather than asserted:
    The judge builds its own retrieval query from what the *plan proposes*
    rather than from the event, and pulls more chunks than the planner did
    (8 against 5). Retrieving toward the plan's own words is how it finds
    passages the plan contradicts, and the wider net is how it finds guidance
    the planner missed. Both are properties of the code, not of the prompt.

Hazard versatility:
    ``hazard`` selects the corpus directory and fills exactly one line of the
    system prompt. No fire vocabulary appears in the dimension definitions, the
    scoring anchors, or the arithmetic — all domain knowledge lives in the
    retrieved corpus. A flood evaluation therefore needs no change to this file:
    only ``data/protocols/flood/``, some flood cases, and ``hazard="flood"``.

    Be aware of the limit, and do not let this file imply otherwise: the
    *pipeline* is not hazard-versatile. RiskAnalysisAgent skips any event whose
    ``event_type`` is not ``"fire"`` and both its prompts are fire-specific. The
    judge will be ready for flood well before the planner is.

The judge deliberately has no web search. It grades against protocol, and a
judge that could look things up would be neither reproducible nor auditable.

Consumed by: research.evaluation.run_response_plan_evaluation
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from research.evaluation.evaluation_schemas import (
    DIMENSION_WEIGHTS,
    MAX_DIMENSION_SCORE,
    PlanVerdict,
    case_score,
)
from ecoguard.analyzers.emergency.fire.risk_analysis_agent import (
    build_evidence_summary,
    render_excerpts,
    section,
)
from ecoguard.shared.llm import (
    ClaudeLLMService,
    ClaudeProviderError,
    build_system_blocks,
)
from ecoguard.shared.protocols import ProtocolRetriever, verify_citations

AGENT_NAME = "ResponsePlanJudgeAgent"

# Deliberately larger than the pipeline's 5. The judge is looking for what the
# plan missed, which requires seeing more of the corpus than the planner did.
DEFAULT_TOP_K = 8

JUDGE_SYSTEM_PROMPT = """\
You are the evaluation component of EcoGuard Agents. You did not write the plan
you are about to read and you have no stake in it.

## What you are judging

Whether this response plan makes operational sense, given the situation
described and the protocol excerpts supplied.

**There is no reference answer.** You are not comparing the plan against a model
solution, because none exists. You are deciding whether a competent operations
officer would act on it.

Consequences of that, which matter:

- **Do not penalise wording, phrasing, or the order of equivalent items.** Two
  plans that differ in words but agree in substance must receive identical
  scores.
- **Do not reward confident writing.** A fluent plan that is wrong scores below
  a plainly written plan that is right.
- Do not penalise a plan for omitting a number, a unit, or a detail it had no
  source for. Working from incomplete evidence is the normal condition here.
- Judge what the plan *does*, not how much it says. Brevity is not a fault.

## Corpus coverage — read this before scoring grounding

The excerpts below are the whole of what this system knows about this hazard. If
they do not cover the scenario in front of you, set `corpus_coverage` to
`does_not_cover` and judge `grounding` on whether the plan **admitted the gap**
— in its assumptions or its actions — rather than on how many passages it cited.

**Do not penalise a plan for failing to cite guidance that does not exist.** A
plan that says "the available protocols do not cover this and the following is
general practice" is behaving correctly and should score well on grounding.

## The five dimensions

Score each from 0 to 4 against these anchors:

- **4** — Sound against both the protocols and the situation. Nothing an
  operations officer would need to change.
- **3** — Sound, with a minor gap that would not change the outcome.
- **2** — A real weakness that would have to be corrected before acting.
- **1** — A serious defect.
- **0** — Wrong in a way that would cause harm or waste resources.

**grounding** — Do the plan's citations actually *support* the actions they are
attached to? (Their existence is already verified mechanically; you are judging
relevance.) Does the plan make protocol-flavoured claims that none of its
citations support? Is there a passage in the excerpts that plainly bears on this
plan and that the plan neither followed nor cited?

**unit_correctness** — Are the recommended units right for this hazard and this
kind of area? Penalise a unit with no role here, and a unit the situation
obviously requires but the plan omits.

**action_quality** — Are the actions specific enough to execute, ordered by
operational priority, and given sensible timeframes? Penalise vague actions, and
an `immediate` timeframe on something that cannot be immediate.

**proportionality** — Does the scale of the response match the assessed risk and
what is actually exposed? **Penalise over-response as heavily as
under-response.** A full mobilisation for a moderate event with nothing exposed
is a failure, not caution.

**safety_criticality** — Would following this plan endanger responders or the
public? Where the protocols make engagement conditional on named safety
preconditions, does the plan state those conditions rather than assuming they
hold? Where people are exposed, does it address warning and evacuation? A plan
that is excellent on every other dimension but commits crews without naming the
preconditions scores low here regardless.

## The units a plan may use

fire_department, police, medical_services, municipal_emergency_team,
home_front_command, aerial_firefighting, forestry_service, utility_operator.

Judge unit correctness against this closed set. A unit outside it cannot appear.

## Your own grounding

Every id in `evidence_chunk_ids` must be copied character-for-character from a
`[chunk_id: ...]` marker in this request. Ids you were not given are discarded.

## Honesty

If the evidence does not let you judge a dimension, score it 2 and say so in the
rationale. Do not guess high to be generous or low to seem rigorous. If the plan
is empty because the pipeline correctly refused to produce one, say so rather
than scoring an absent plan as a bad plan.
"""


class ResponsePlanJudgeAgent:
    """
    Grades response plans against a hazard's protocol corpus.

    Attributes:
        hazard (str): Which corpus to judge against.
        llm_service: Anything exposing ``available`` and ``parse_structured``.
        retriever: Anything exposing ``retrieve(query, top_k) -> list[dict]``.
            A separate instance from the pipeline's, on purpose.
        top_k (int): Chunks retrieved per case.
    """

    def __init__(
        self,
        *,
        llm_service: object | None = None,
        retriever: object | None = None,
        top_k: int = DEFAULT_TOP_K,
        hazard: str = "fire",
    ) -> None:
        self.hazard = hazard
        self.llm_service = llm_service if llm_service is not None else ClaudeLLMService()
        self.retriever = (
            retriever if retriever is not None else ProtocolRetriever(hazard=hazard)
        )
        self.top_k = top_k

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def judge_case(
        self, *, case: dict, risk_assessment: dict, response_plan: dict
    ) -> dict:
        """
        Judge one response plan.

        Args:
            case (dict): The evaluation case. Only its identity is used; the
                author's notes are deliberately never shown to the judge.
            risk_assessment (dict): What the risk agent produced.
            response_plan (dict): What the planner produced.

        Returns:
            dict: A verdict. case_score is None on every non-success path —
                never 0.0, which would be indistinguishable from "the plan was
                terrible".
        """
        case_id = (case or {}).get("case_id")
        event = (case or {}).get("detected_event") or {}
        event_id = (response_plan or {}).get("event_id")

        planning_status = section(response_plan, "metadata").get("planning_status")

        # The refusal check runs before anything else and costs nothing. A
        # pipeline that correctly declined to plan must not be graded as though
        # it produced a bad plan.
        if planning_status != "success":
            return self.build_refusal_verdict(
                case_id=case_id,
                event_id=event_id,
                risk_assessment=risk_assessment,
                response_plan=response_plan,
            )

        if not getattr(self.llm_service, "available", False):
            return self.build_failed_verdict(case_id, event_id, "missing credentials")

        query = self.build_query(
            detected_event=event,
            risk_assessment=risk_assessment,
            response_plan=response_plan,
        )
        chunks = self.retriever.retrieve(query, top_k=self.top_k)

        if not chunks:
            corpus_loaded = getattr(self.retriever, "available", True)
            error = "no protocol match" if corpus_loaded else "protocol corpus unavailable"
            logging.error("Judging aborted before the model call: %s", error)
            return self.build_failed_verdict(case_id, event_id, error)

        audit = self.audit_plan_citations(response_plan)

        system_blocks, user_text = self.build_prompt(
            detected_event=event,
            risk_assessment=risk_assessment,
            response_plan=response_plan,
            chunks=chunks,
            citation_audit=audit,
        )

        try:
            verdict = self.llm_service.parse_structured(
                system_blocks=system_blocks,
                user_text=user_text,
                output_format=PlanVerdict,
            )
        except ClaudeProviderError as error:
            logging.error("Judging model call failed: %s", error)
            return self.build_failed_verdict(case_id, event_id, str(error))

        return self.build_verdict(
            case_id=case_id,
            event_id=event_id,
            payload=verdict.model_dump(mode="json"),
            chunks=chunks,
            citation_audit=audit,
        )

    def judge_suite(self, case_results: list[dict]) -> dict:
        """
        Aggregate per-case verdicts into a suite result. No model call.

        The suite score is the mean over **judged cases only**. A provider
        outage or a pipeline failure is reported separately rather than averaged
        in as a zero, because averaging infrastructure problems into a quality
        score manufactures a signal that is not there.

        Args:
            case_results (list[dict]): judge_case outputs.

        Returns:
            dict: Suite summary. suite_score is None when nothing was judged.
        """
        judged = [
            r for r in case_results
            if section(r, "metadata").get("judging_status") == "success"
        ]

        refusals = [r for r in case_results if r.get("refusal_correct") is True]
        pipeline_failed = [r for r in case_results if r.get("refusal_correct") is False]
        judge_failed = [
            r for r in case_results
            if section(r, "metadata").get("judging_status") == "failed"
        ]

        scores = [r["case_score"] for r in judged if r.get("case_score") is not None]

        dimension_means: dict[str, float] = {}
        for name in DIMENSION_WEIGHTS:
            values = [
                r["dimension_scores"][name]
                for r in judged
                if name in (r.get("dimension_scores") or {})
            ]
            if values:
                dimension_means[name] = round(
                    sum(values) / len(values) / MAX_DIMENSION_SCORE, 3
                )

        verdict_counts: dict[str, int] = {}
        for result in judged:
            key = result.get("verdict") or "unknown"
            verdict_counts[key] = verdict_counts.get(key, 0) + 1

        return {
            "hazard": self.hazard,
            "suite_score": round(sum(scores) / len(scores), 3) if scores else None,
            "cases_total": len(case_results),
            "cases_judged": len(judged),
            "cases_refusal_correct": len(refusals),
            "cases_pipeline_failed": len(pipeline_failed),
            "cases_judge_failed": len(judge_failed),
            "verdict_counts": verdict_counts,
            "dimension_means": dimension_means,
            "weakest_dimension": (
                min(dimension_means, key=dimension_means.get)
                if dimension_means
                else None
            ),
            "not_judged": [
                {
                    "case_id": r.get("case_id"),
                    "reason": section(r, "metadata").get("reason") or r.get("error"),
                }
                for r in case_results
                if section(r, "metadata").get("judging_status") != "success"
            ],
        }

    # ------------------------------------------------------------------
    # Retrieval and auditing
    # ------------------------------------------------------------------

    def build_query(
        self, *, detected_event: dict, risk_assessment: dict, response_plan: dict
    ) -> str:
        """
        Build the judge's own retrieval query.

        Deliberately assembled from what the plan **proposes** rather than from
        what the event contains. Retrieving toward the plan's own language is
        what surfaces passages the plan contradicts; retrieving from the event
        would mostly rediscover what the planner already saw.

        Args:
            detected_event (dict): The event.
            risk_assessment (dict): The assessment.
            response_plan (dict): The plan under evaluation.

        Returns:
            str: A bag of terms for BM25.
        """
        terms = [
            f"{self.hazard} response protocol proportionate response incident command",
            # Fetched unconditionally: safety is the heaviest dimension, so the
            # safety doctrine must be in front of the judge whether or not the
            # plan happened to mention it. A plan that omits safety entirely is
            # exactly the one this needs to catch.
            "responder safety preconditions escape routes safety zones "
            "acceptable risk engagement",
        ]

        for unit in response_plan.get("recommended_units") or []:
            terms.append(str(unit).replace("_", " "))

        for action in response_plan.get("response_actions") or []:
            words = str(action.get("action", "")).split()[:10]
            if words:
                terms.append(" ".join(words))

        summary_words = str(response_plan.get("plan_summary") or "").split()[:15]
        if summary_words:
            terms.append(" ".join(summary_words))

        if risk_assessment.get("risk_level"):
            terms.append(f"{risk_assessment['risk_level']} risk")

        area_type = section(risk_assessment, "situational_context").get("area_type")
        if area_type and area_type != "unknown":
            terms.append(str(area_type).replace("_", " "))

        return " ".join(terms)

    def audit_plan_citations(self, response_plan: dict) -> dict | None:
        """
        Check the plan's citations against the whole corpus.

        Deliberately not against the judge's own top-k: a perfectly legitimate
        citation would be marked bogus purely because the judge's retrieval
        happened not to include that chunk. Checking the full corpus is both
        fairer and stricter than the pipeline's own check, which only sees one
        request's retrieval.

        Args:
            response_plan (dict): The plan under evaluation.

        Returns:
            dict | None: Counts, or None when the retriever exposes no chunks.
                None rather than zeros — an unaudited plan is not a clean one.
        """
        corpus_chunks = getattr(self.retriever, "chunks", None)

        if not corpus_chunks:
            return None

        claimed = (section(response_plan, "grounding").get("citations")) or []
        verified, dropped = verify_citations(claimed, corpus_chunks)

        return {
            "claimed": len(claimed),
            "verified_against_corpus": len(verified),
            "unverifiable": dropped,
        }

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def build_prompt(
        self,
        *,
        detected_event: dict,
        risk_assessment: dict,
        response_plan: dict,
        chunks: list[dict],
        citation_audit: dict | None,
    ) -> tuple[list[dict], str]:
        """
        Build the judge's system blocks and user message.

        The author's `notes`, `probes` and `expected_behaviour_notes` are never
        included. Showing them would turn this into the rubric-based evaluation
        the design deliberately rejects — the judge is meant to reason from
        protocol, not to check answers against a crib.

        Returns:
            tuple[list[dict], str]: System blocks and user text.
        """
        user_text = "\n\n".join(
            [
                f"# Hazard\n\n{self.hazard}",
                "# The event\n\n" + build_evidence_summary(detected_event),
                "# The risk assessment the plan was built from\n\n"
                + self.render_assessment(risk_assessment),
                "# The response plan under evaluation\n\n"
                + self.render_plan(response_plan, citation_audit),
                "# Protocol excerpts you retrieved\n\n"
                "These are the whole of what this system knows about this hazard. "
                "Cite only from these.\n\n" + render_excerpts(chunks),
                "# Task\n\n"
                "Judge the plan. Score each of the five dimensions, say what the "
                "plan got right and wrong, and name any protocol point in the "
                "excerpts that plainly bears on this plan and that the plan "
                "neither followed nor cited.",
            ]
        )

        return build_system_blocks(JUDGE_SYSTEM_PROMPT), user_text

    @staticmethod
    def render_assessment(risk_assessment: dict) -> str:
        """Render the assessment as context for judging the plan."""
        lines = [
            f"- Risk score: {risk_assessment.get('risk_score')} / 100 "
            f"({risk_assessment.get('risk_level')})",
            f"- Assessment confidence: {risk_assessment.get('confidence')}",
        ]

        context = section(risk_assessment, "situational_context")
        if context:
            lines.append(f"- Area type: {context.get('area_type')}")
            lines.append(
                f"- Population nearby: {context.get('population_band')} "
                f"(basis: {context.get('population_basis')})"
            )
            lines.append(
                f"- Evacuation consideration: {context.get('evacuation_consideration')}"
            )

        for driver in risk_assessment.get("primary_drivers") or []:
            lines.append(f"- Driver: {driver}")

        for gap in risk_assessment.get("evidence_gaps") or []:
            lines.append(f"- Evidence gap: {gap}")

        findings = risk_assessment.get("web_findings") or []
        if findings:
            lines.append(
                "- Some facts below were looked up externally rather than collected, "
                "and are weaker evidence than measured data:"
            )
            for finding in findings:
                lines.append(f"  - {finding.get('fact')} [{finding.get('source_title')}]")

        if risk_assessment.get("explanation"):
            lines.append(f"- Rationale: {risk_assessment['explanation']}")

        return "\n".join(lines)

    @staticmethod
    def render_plan(response_plan: dict, citation_audit: dict | None) -> str:
        """Render the plan, annotated with how its citations audited."""
        units = response_plan.get("recommended_units") or []
        lines = [f"- Units recommended: {', '.join(units) if units else 'none'}"]

        if response_plan.get("plan_summary"):
            lines.append(f"- Summary: {response_plan['plan_summary']}")

        lines.append("- Actions, in the order given:")
        for index, action in enumerate(response_plan.get("response_actions") or [], 1):
            lines.append(
                f"  {index}. [{action.get('timeframe')}] "
                f"{action.get('responsible_unit')}: {action.get('action')}"
            )

        for assumption in response_plan.get("assumptions") or []:
            lines.append(f"- Assumption stated: {assumption}")

        citations = (section(response_plan, "grounding").get("citations")) or []
        if citations:
            lines.append("- Protocol passages the plan cited:")
            for citation in citations:
                lines.append(
                    f"  - [{citation.get('chunk_id')}] supporting: "
                    f"{citation.get('supports')}"
                )
                lines.append(f"    \"{citation.get('quoted_text')}\"")

        if citation_audit is None:
            lines.append(
                "- Citation audit: not performed, so treat the citations above as "
                "unchecked."
            )
        else:
            lines.append(
                f"- Citation audit: {citation_audit['verified_against_corpus']} of "
                f"{citation_audit['claimed']} verified against the corpus, "
                f"{citation_audit['unverifiable']} could not be verified."
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Verdict builders
    # ------------------------------------------------------------------

    def build_verdict(
        self,
        *,
        case_id: str | None,
        event_id: str | None,
        payload: dict,
        chunks: list[dict],
        citation_audit: dict | None,
    ) -> dict:
        """Build a successful verdict from a validated model response."""
        dimension_scores = {d["dimension"]: d["score"] for d in payload["dimensions"]}
        rationales = {d["dimension"]: d["rationale"] for d in payload["dimensions"]}

        retrieved = {chunk["chunk_id"] for chunk in chunks}
        unknown_ids = 0
        for item in payload["dimensions"]:
            unknown_ids += sum(
                1 for cid in item["evidence_chunk_ids"] if cid not in retrieved
            )

        return {
            "metadata": {
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "judging_status": "success",
                "model": getattr(self.llm_service, "model", None),
                "reason": None,
                "hazard": self.hazard,
            },
            "case_id": case_id,
            "event_id": event_id,
            "verdict": payload["verdict"],
            "case_score": case_score(dimension_scores),
            "dimension_scores": dimension_scores,
            "dimension_rationales": rationales,
            "corpus_coverage": payload["corpus_coverage"],
            "strengths": payload["strengths"],
            "problems": payload["problems"],
            "missed_protocol_points": payload["missed_protocol_points"],
            "summary": payload["summary"],
            "refusal_correct": None,
            "citation_audit": citation_audit,
            "judge_grounding": {
                "retriever": "bm25",
                "hazard": self.hazard,
                "retrieved_chunk_ids": sorted(retrieved),
                # Dropped rather than fatal: unlike the pipeline's citations,
                # these are supporting detail, and discarding a useful diagnostic
                # over a copied-id typo would lose more than it protects. The
                # count surfaces a systematically sloppy judge.
                "unverified_evidence_id_count": unknown_ids,
            },
            "error": None,
        }

    def build_refusal_verdict(
        self,
        *,
        case_id: str | None,
        event_id: str | None,
        risk_assessment: dict,
        response_plan: dict,
    ) -> dict:
        """
        Judge a case where no plan was produced. No model call.

        Two very different situations share this shape:

        - Risk analysis also did not succeed, so there was nothing to plan from
          and refusing was correct.
        - Risk analysis succeeded but planning failed anyway, which is a
          pipeline defect.

        Both are excluded from the suite score and reported separately, because
        neither is evidence about plan quality.
        """
        analysis_ok = (
            section(risk_assessment, "metadata").get("analysis_status") == "success"
        )
        refusal_correct = not analysis_ok

        return {
            "metadata": {
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "judging_status": "skipped",
                "model": None,
                "reason": (
                    "pipeline correctly declined to plan"
                    if refusal_correct
                    else "planning failed despite a successful assessment"
                ),
                "hazard": self.hazard,
            },
            "case_id": case_id,
            "event_id": event_id,
            "verdict": "not_applicable",
            "case_score": None,
            "dimension_scores": {},
            "dimension_rationales": {},
            "corpus_coverage": None,
            "strengths": [],
            "problems": [],
            "missed_protocol_points": [],
            "summary": None,
            "refusal_correct": refusal_correct,
            "citation_audit": None,
            "judge_grounding": None,
            "error": response_plan.get("error"),
        }

    def build_failed_verdict(
        self, case_id: str | None, event_id: str | None, error: str
    ) -> dict:
        """Build a verdict for a case the judge could not evaluate."""
        return {
            "metadata": {
                "timestamp": self._timestamp(),
                "agent": AGENT_NAME,
                "judging_status": "failed",
                "model": None,
                "reason": None,
                "hazard": self.hazard,
            },
            "case_id": case_id,
            "event_id": event_id,
            "verdict": None,
            # None, never 0.0. A zero would be read as "this plan was terrible"
            # when what happened is that we could not look at it.
            "case_score": None,
            "dimension_scores": {},
            "dimension_rationales": {},
            "corpus_coverage": None,
            "strengths": [],
            "problems": [],
            "missed_protocol_points": [],
            "summary": None,
            "refusal_correct": None,
            "citation_audit": None,
            "judge_grounding": None,
            "error": error,
        }

    @staticmethod
    def _timestamp() -> str:
        """UTC timestamp in the format every other agent in this project uses."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
