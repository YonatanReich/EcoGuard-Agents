"""
Offline tests for the response plan judging agent.

Fakes for both collaborators, no network, no model. The properties worth
defending here are the ones that decide whether a score means anything:

- A pipeline that correctly refused to plan must not be graded as though it
  produced a bad plan, and must cost nothing.
- A case the judge could not evaluate must score None, never 0.0.
- The author's expected-behaviour notes must never reach the judge, or the whole
  design collapses into the rubric evaluation it deliberately avoids.
- The judge's retrieval must genuinely differ from the planner's, since that is
  the only mechanism by which it can catch something the planner missed.

Run with: pytest
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from research.evaluation.evaluation_schemas import DIMENSION_WEIGHTS, PlanVerdict, case_score
from ecoguard.response_planner.fire.plan_judge import ResponsePlanJudgeAgent
from ecoguard.shared.llm import ClaudeProviderError

from tests.test_risk_analysis_agent import (  # shared fakes, per the house precedent
    CHUNK,
    CHUNK_TEXT,
    FakeLLM,
    FakeRetriever,
    detected_event,
)


class ChunkedFakeRetriever(FakeRetriever):
    """A retriever exposing .chunks, as the real one does."""

    def __init__(self, chunks=None, available=True) -> None:
        super().__init__(chunks=chunks, available=available)
        self.chunks = list(self.chunks) if isinstance(self.chunks, list) else []


class ChunklessRetriever:
    """
    A retriever with no .chunks at all.

    Stands in for an injected replacement that implements only the documented
    swap seam — `.retrieve(query, top_k)` — and therefore cannot support a
    corpus-wide citation audit.
    """

    available = True

    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query, top_k=5):
        self.queries.append(query)
        return [dict(CHUNK)]


SUCCESSFUL_RISK = {
    "metadata": {"analysis_status": "success", "agent": "RiskAnalysisAgent"},
    "event_id": "abc123456789",
    "risk_score": 78,
    "risk_level": "high",
    "confidence": "medium",
    "situational_context": {
        "area_type": "wildland_urban_interface",
        "population_band": "1k_to_10k",
        "population_basis": "osm_population_tag",
        "evacuation_consideration": "localised_evacuation",
    },
    "primary_drivers": ["very high FWI class"],
    "evidence_gaps": [],
    "explanation": "Very high fire danger with wind supporting spread.",
    "web_findings": [],
}

SUCCESSFUL_PLAN = {
    "metadata": {"planning_status": "success", "agent": "ResponsePlanningAgent"},
    "event_id": "abc123456789",
    "recommended_units": ["fire_department", "police"],
    "response_actions": [
        {
            "action": "Establish incident command and confirm escape routes before committing crews.",
            "responsible_unit": "fire_department",
            "timeframe": "immediate",
        },
        {
            "action": "Close Route 4 at the eastern junction and stage traffic control.",
            "responsible_unit": "police",
            "timeframe": "within_1_hour",
        },
    ],
    "plan_summary": "Protect the settlement and contain the eastern flank.",
    "assumptions": ["The detection reflects an actively burning fire."],
    "grounding": {
        "citations": [
            {
                "chunk_id": CHUNK["chunk_id"],
                "document_title": "Structure Triage in the WUI",
                "quoted_text": "The minimum radius of defensible space should be 30 feet.",
                "supports": "Structure protection standoff",
            }
        ]
    },
    "error": None,
}

CASE = {
    "case_id": "fire-03-carmel-wui-extreme",
    "detected_event": detected_event(),
    "notes": "AUTHOR_ONLY_NOTES_SENTINEL",
    "probes": ["PROBE_SENTINEL"],
    "expected_behaviour_notes": "EXPECTED_BEHAVIOUR_SENTINEL",
}


def build_verdict_payload(**overrides) -> PlanVerdict:
    """A schema-valid verdict."""
    payload = {
        "verdict": "sound_with_reservations",
        "dimensions": [
            {
                "dimension": name,
                "score": 3,
                "rationale": f"The plan handles {name} adequately but not perfectly.",
                "evidence_chunk_ids": [CHUNK["chunk_id"]],
            }
            for name in DIMENSION_WEIGHTS
        ],
        "corpus_coverage": "covers_this_scenario",
        "strengths": ["Escape routes named before committing crews"],
        "problems": ["No mention of utility isolation"],
        "missed_protocol_points": ["Defensible space standoff not applied"],
        "summary": "A workable plan with one real omission around utility isolation.",
    }
    payload.update(overrides)
    return PlanVerdict(**payload)


def build_judge(llm=None, retriever=None, **kwargs) -> ResponsePlanJudgeAgent:
    return ResponsePlanJudgeAgent(
        llm_service=llm if llm is not None else FakeLLM(build_verdict_payload()),
        retriever=retriever if retriever is not None else ChunkedFakeRetriever(),
        **kwargs,
    )


# --------------------------------------------------------------------------
# The refusal path — must cost nothing
# --------------------------------------------------------------------------


def test_correct_refusal_is_recognised_and_costs_nothing():
    """
    The gate case. Risk was skipped, so there was nothing to plan from.

    Scoring an absent plan as a bad plan would punish the pipeline for behaving
    correctly, and would make the honest-refusal property invisible in the
    suite score.
    """
    llm = FakeLLM(build_verdict_payload())
    retriever = ChunkedFakeRetriever()
    judge = build_judge(llm=llm, retriever=retriever)

    result = judge.judge_case(
        case=CASE,
        risk_assessment={"metadata": {"analysis_status": "skipped"}},
        response_plan={"metadata": {"planning_status": "skipped"}, "error": None},
    )

    assert result["verdict"] == "not_applicable"
    assert result["refusal_correct"] is True
    assert result["case_score"] is None
    assert llm.calls == []
    assert retriever.queries == []


def test_planning_failure_after_a_good_assessment_is_a_pipeline_defect():
    """Same empty plan, opposite meaning: this one should have been plannable."""
    judge = build_judge()

    result = judge.judge_case(
        case=CASE,
        risk_assessment=SUCCESSFUL_RISK,
        response_plan={"metadata": {"planning_status": "failed"}, "error": "timeout"},
    )

    assert result["refusal_correct"] is False
    assert result["case_score"] is None
    assert result["error"] == "timeout"


# --------------------------------------------------------------------------
# Degradation
# --------------------------------------------------------------------------


def test_missing_credentials_fails_before_retrieval():
    retriever = ChunkedFakeRetriever()
    judge = build_judge(
        llm=FakeLLM(build_verdict_payload(), available=False), retriever=retriever
    )

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert result["metadata"]["judging_status"] == "failed"
    assert result["error"] == "missing credentials"
    assert result["case_score"] is None
    assert retriever.queries == []


def test_empty_retrieval_fails_before_the_model_call():
    llm = FakeLLM(build_verdict_payload())
    judge = build_judge(llm=llm, retriever=ChunkedFakeRetriever(chunks=[]))

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert result["error"] == "no protocol match"
    assert llm.calls == []


def test_unavailable_corpus_reports_a_distinct_error():
    judge = build_judge(retriever=ChunkedFakeRetriever(chunks=[], available=False))

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert result["error"] == "protocol corpus unavailable"


@pytest.mark.parametrize("kind", ["timeout", "rate limited", "malformed response"])
def test_provider_errors_propagate_their_category(kind):
    judge = build_judge(llm=FakeLLM(ClaudeProviderError(kind)))

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert result["metadata"]["judging_status"] == "failed"
    assert result["error"] == kind
    assert result["case_score"] is None


# --------------------------------------------------------------------------
# The success path and the arithmetic
# --------------------------------------------------------------------------


def test_successful_verdict_shape_and_exact_score():
    """
    The score is pinned to a hand-computed value.

    All fives at 3/4 gives 0.75 exactly; if the weights or the normalisation
    drift, every historical score silently changes meaning.
    """
    judge = build_judge()

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert result["metadata"]["judging_status"] == "success"
    assert result["case_score"] == 0.75
    assert set(result["dimension_scores"]) == set(DIMENSION_WEIGHTS)
    assert result["dimension_rationales"]["safety_criticality"]


def test_result_is_json_serialisable():
    judge = build_judge()

    json.dumps(
        judge.judge_case(
            case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
        )
    )


def test_unknown_evidence_ids_are_dropped_and_counted_not_fatal():
    """
    A copied-id typo must not destroy an otherwise useful diagnostic.

    Unlike the pipeline's citations, the judge's evidence ids are supporting
    detail rather than the basis of a life-safety instruction, so they are
    counted rather than enforced.
    """
    verdict = build_verdict_payload(
        dimensions=[
            {
                "dimension": name,
                "score": 3,
                "rationale": f"Adequate handling of {name} in this plan overall.",
                "evidence_chunk_ids": ["totally-made-up#chunk#0"],
            }
            for name in DIMENSION_WEIGHTS
        ]
    )
    judge = build_judge(llm=FakeLLM(verdict))

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert result["metadata"]["judging_status"] == "success"
    assert result["judge_grounding"]["unverified_evidence_id_count"] == 5


# --------------------------------------------------------------------------
# Independence and leak-proofing
# --------------------------------------------------------------------------


def test_author_notes_never_reach_the_judge():
    """
    The single most important guard in this file.

    Showing the judge what a good answer looks like would turn a protocol-based
    evaluation into a rubric comparison, which is exactly the design the project
    rejected. Sentinel strings make the leak impossible to miss.
    """
    llm = FakeLLM(build_verdict_payload())
    judge = build_judge(llm=llm)

    judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    prompt = llm.calls[0]["user_text"] + llm.calls[0]["system_blocks"][0]["text"]

    assert "EXPECTED_BEHAVIOUR_SENTINEL" not in prompt
    assert "AUTHOR_ONLY_NOTES_SENTINEL" not in prompt
    assert "PROBE_SENTINEL" not in prompt


def test_judge_query_is_built_from_the_plan_not_the_event():
    """
    Independence is mechanical, not asserted.

    Retrieving toward the plan's own wording is how the judge finds passages the
    plan contradicts. A query built from the event would mostly rediscover what
    the planner already saw.
    """
    retriever = ChunkedFakeRetriever()
    judge = build_judge(retriever=retriever)

    judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    query = retriever.queries[0]

    assert "Close Route 4 at the eastern junction" in query
    assert "fire department" in query
    assert "police" in query


def test_safety_doctrine_is_retrieved_unconditionally():
    """
    Safety is the heaviest dimension, so its doctrine must always be in view.

    A plan that omits safety entirely is exactly the one that would otherwise
    never pull the safety passages into the judge's context.
    """
    retriever = ChunkedFakeRetriever()
    judge = build_judge(retriever=retriever)

    silent_plan = {
        **SUCCESSFUL_PLAN,
        "response_actions": [],
        "plan_summary": "Do something.",
        "recommended_units": ["fire_department"],
    }
    judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=silent_plan
    )

    assert "safety" in retriever.queries[0]


def test_judge_pulls_more_chunks_than_the_pipeline():
    """The wider net is how it finds what the planner missed."""
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import DEFAULT_TOP_K as PIPELINE_TOP_K

    assert build_judge().top_k > PIPELINE_TOP_K


# --------------------------------------------------------------------------
# Citation auditing
# --------------------------------------------------------------------------


def test_plan_citations_are_audited_against_the_whole_corpus():
    judge = build_judge()

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert result["citation_audit"] == {
        "claimed": 1,
        "verified_against_corpus": 1,
        "unverifiable": 0,
    }


def test_a_fabricated_plan_citation_is_caught():
    plan = {
        **SUCCESSFUL_PLAN,
        "grounding": {
            "citations": [
                {
                    "chunk_id": "invented#chunk#0",
                    "document_title": "Authoritative Sounding Manual",
                    "quoted_text": "All units shall respond without delay in every case.",
                    "supports": "everything",
                }
            ]
        },
    }
    judge = build_judge()

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=plan
    )

    assert result["citation_audit"]["unverifiable"] == 1
    assert result["citation_audit"]["verified_against_corpus"] == 0


def test_audit_is_none_when_the_retriever_exposes_no_chunks():
    """
    None, not zeros.

    An unaudited plan is not a clean plan, and reporting 0 unverifiable would
    say the citations checked out when nothing was checked.
    """
    judge = build_judge(retriever=ChunklessRetriever())

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert result["citation_audit"] is None


def test_unaudited_citations_are_flagged_to_the_judge():
    llm = FakeLLM(build_verdict_payload())
    judge = build_judge(llm=llm, retriever=ChunklessRetriever())

    judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert "unchecked" in llm.calls[0]["user_text"]


# --------------------------------------------------------------------------
# Suite aggregation
# --------------------------------------------------------------------------


def judged(score: float, verdict: str = "sound", **dims) -> dict:
    scores = {name: 3 for name in DIMENSION_WEIGHTS}
    scores.update(dims)
    return {
        "metadata": {"judging_status": "success"},
        "case_id": "c",
        "verdict": verdict,
        "case_score": score,
        "dimension_scores": scores,
        "refusal_correct": None,
    }


def test_suite_score_averages_only_judged_cases():
    """
    A provider outage is not evidence about plan quality.

    Averaging a failure in as a zero would manufacture a quality signal out of
    an infrastructure problem — the same fabrication the pipeline refuses.
    """
    judge = build_judge()

    summary = judge.judge_suite(
        [
            judged(0.8),
            judged(0.6),
            {"metadata": {"judging_status": "failed"}, "case_score": None,
             "refusal_correct": None, "case_id": "x"},
        ]
    )

    assert summary["suite_score"] == 0.7
    assert summary["cases_judged"] == 2
    assert summary["cases_judge_failed"] == 1
    assert summary["cases_total"] == 3


def test_refusals_are_counted_separately_not_scored():
    judge = build_judge()

    summary = judge.judge_suite(
        [
            judged(0.9),
            {"metadata": {"judging_status": "skipped"}, "case_score": None,
             "refusal_correct": True, "case_id": "gate"},
        ]
    )

    assert summary["suite_score"] == 0.9
    assert summary["cases_refusal_correct"] == 1
    assert summary["cases_judged"] == 1


def test_pipeline_failures_are_counted_separately():
    judge = build_judge()

    summary = judge.judge_suite(
        [
            judged(0.9),
            {"metadata": {"judging_status": "skipped"}, "case_score": None,
             "refusal_correct": False, "case_id": "broken"},
        ]
    )

    assert summary["cases_pipeline_failed"] == 1


def test_all_failed_suite_scores_none_not_zero():
    """Nothing was measured, so there is no number to report."""
    judge = build_judge()

    summary = judge.judge_suite(
        [{"metadata": {"judging_status": "failed"}, "case_score": None,
          "refusal_correct": None, "case_id": "x"}]
    )

    assert summary["suite_score"] is None
    assert summary["cases_judged"] == 0


def test_weakest_dimension_is_identified():
    """The headline answer to 'where is the pipeline weak'."""
    judge = build_judge()

    summary = judge.judge_suite(
        [judged(0.5, safety_criticality=1), judged(0.5, safety_criticality=1)]
    )

    assert summary["weakest_dimension"] == "safety_criticality"
    assert summary["dimension_means"]["safety_criticality"] == 0.25


def test_empty_suite_is_safe():
    summary = build_judge().judge_suite([])

    assert summary["suite_score"] is None
    assert summary["cases_total"] == 0


# --------------------------------------------------------------------------
# Hazard versatility
# --------------------------------------------------------------------------


def test_hazard_appears_in_metadata_and_the_prompt():
    llm = FakeLLM(build_verdict_payload())
    judge = build_judge(llm=llm, hazard="flood")

    result = judge.judge_case(
        case=CASE, risk_assessment=SUCCESSFUL_RISK, response_plan=SUCCESSFUL_PLAN
    )

    assert result["metadata"]["hazard"] == "flood"
    assert "flood" in llm.calls[0]["user_text"]


def test_system_prompt_carries_no_fire_vocabulary():
    """
    Domain knowledge belongs in the corpus, not the rubric.

    If fire terms leaked into the dimension definitions, the judge would carry
    fire assumptions into a flood evaluation.
    """
    from ecoguard.response_planner.fire.plan_judge import JUDGE_SYSTEM_PROMPT

    lowered = JUDGE_SYSTEM_PROMPT.lower()

    for term in ("wildfire", "fwi", "defensible space", "hotspot", "firms"):
        assert term not in lowered, f"fire-specific term in the judge rubric: {term}"


def test_judge_uses_a_hazard_scoped_corpus_by_default():
    judge = ResponsePlanJudgeAgent(llm_service=FakeLLM(None), hazard="flood")

    assert judge.retriever.hazard == "flood"
    assert judge.retriever.available is False   # no flood corpus committed yet


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


def test_too_few_dimensions_is_rejected():
    """
    An incomplete answer must fail rather than be averaged over four.

    Otherwise it produces a score that looks comparable to a complete one.
    Caught by the list length before the completeness validator is reached.
    """
    with pytest.raises(ValidationError, match="at least 5"):
        build_verdict_payload(
            dimensions=[
                {"dimension": "grounding", "score": 3,
                 "rationale": "Only one dimension supplied here in this answer."}
            ]
        )


def test_duplicated_dimension_is_rejected():
    """
    Five entries, but the same one five times.

    This is what the completeness validator exists for: the count is right, so
    a length check alone would let it through, and the missing four dimensions
    would silently score nothing.
    """
    with pytest.raises(ValidationError, match="exactly once"):
        build_verdict_payload(
            dimensions=[
                {"dimension": "grounding", "score": 3,
                 "rationale": "Duplicated dimension entry number one here."}
            ] * 5
        )


def test_the_validator_names_what_is_missing():
    """A rejection should say which dimensions were absent."""
    dimensions = [
        {"dimension": name, "score": 3,
         "rationale": f"Adequate handling of {name} in this response plan."}
        for name in list(DIMENSION_WEIGHTS)[:4]
    ]
    dimensions.append(dict(dimensions[0]))   # pad to five with a duplicate

    with pytest.raises(ValidationError, match="missing="):
        build_verdict_payload(dimensions=dimensions)


def test_weights_sum_to_one():
    assert round(sum(DIMENSION_WEIGHTS.values()), 6) == 1.0


@pytest.mark.parametrize("score,expected", [(4, 1.0), (0, 0.0), (2, 0.5)])
def test_uniform_scores_normalise_predictably(score, expected):
    assert case_score({name: score for name in DIMENSION_WEIGHTS}) == expected
