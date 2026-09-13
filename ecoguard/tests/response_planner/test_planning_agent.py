"""
Offline tests for the response planning agent.

Same injection approach as the risk agent tests: fake LLM, fake retriever, no
network. The emphasis here is on the hard gate — planning must never run on an
event whose risk was not successfully assessed — and on the plan's internal
coherence.

Run with: pytest
"""

from __future__ import annotations

import json

import pytest

from ecoguard.response_planner.fire.planning_agent import ResponsePlanningAgent
from ecoguard.shared.schemas import ResponsePlan
from ecoguard.shared.llm import ClaudeProviderError

from tests.test_risk_analysis_agent import (  # reuse the shared fakes
    CHUNK,
    FakeLLM,
    FakeRetriever,
    detected_event,
)


def build_valid_plan(**overrides) -> ResponsePlan:
    """A schema-valid plan whose citation quotes the fake chunk verbatim."""
    payload = {
        "recommended_units": ["fire_department", "police"],
        "actions": [
            {
                "action": "Establish incident command and confirm escape routes.",
                "responsible_unit": "fire_department",
                "timeframe": "immediate",
            },
            {
                "action": "Close Route 4 at the eastern junction and stage traffic control.",
                "responsible_unit": "police",
                "timeframe": "within_1_hour",
            },
        ],
        "plan_summary": "Protect Givat Shmuel and contain the eastern flank.",
        "assumptions": ["The detection reflects an actively burning fire."],
        "protocol_citations": [
            {
                "chunk_id": CHUNK["chunk_id"],
                "document_title": "Structure Triage in the WUI",
                "quoted_text": "The minimum radius of defensible space should be 30 feet.",
                "supports": "Structure protection standoff for the settlement",
            }
        ],
    }
    payload.update(overrides)
    return ResponsePlan(**payload)


def successful_assessment(**overrides) -> dict:
    """A risk assessment in the shape RiskAnalysisAgent returns on success."""
    assessment = {
        "metadata": {
            "timestamp": "2026-08-27T09:00:00Z",
            "agent": "RiskAnalysisAgent",
            "analysis_status": "success",
            "model": "claude-sonnet-5",
            "reason": None,
        },
        "event_id": "a3f19c2b8d04",
        "event_type": "fire",
        "location": {"latitude": 31.9, "longitude": 34.8},
        "risk_score": 78,
        "risk_level": "high",
        # Labels which kind of risk this is; FireRiskPredictionAgent emits the
        # same field names on a 0.0-1.0 scale with different meaning.
        "risk_semantics": "detected_event_operational_risk",
        "confidence": "medium",
        "primary_drivers": ["very high FWI class", "wind 34 km/h"],
        "explanation": "Very high fire danger with wind supporting rapid spread.",
        "evidence_gaps": [],
        "grounding": {
            "retriever": "bm25",
            "retrieved_chunk_ids": [CHUNK["chunk_id"]],
            "citations": [
                {
                    "chunk_id": CHUNK["chunk_id"],
                    "document_title": "Structure Triage in the WUI",
                    "supports": "Exposure judgement",
                }
            ],
            "unverified_citation_count": 0,
        },
        "error": None,
    }
    assessment.update(overrides)
    return assessment


def build_agent(llm=None, retriever=None) -> ResponsePlanningAgent:
    return ResponsePlanningAgent(
        llm_service=llm if llm is not None else FakeLLM(build_valid_plan()),
        retriever=retriever if retriever is not None else FakeRetriever(),
    )


# --------------------------------------------------------------------------
# The hard gate
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_planning_is_skipped_unless_risk_analysis_succeeded(status):
    """
    Planning a response to a risk we could not determine is fabrication.

    An operator could act on the result, which makes this the most consequential
    guard in the module. It also saves a model call on every no-event scan.
    """
    llm = FakeLLM(build_valid_plan())
    retriever = FakeRetriever()
    agent = build_agent(llm=llm, retriever=retriever)

    assessment = successful_assessment()
    assessment["metadata"]["analysis_status"] = status

    result = agent.plan_response(detected_event(), assessment)

    assert result["metadata"]["planning_status"] == "skipped"
    assert result["metadata"]["reason"] == "risk_analysis_unavailable"
    assert llm.calls == []
    assert retriever.queries == []


@pytest.mark.parametrize("assessment", [None, {}, "not a dict", {"metadata": None}])
def test_malformed_assessments_are_skipped_not_crashed(assessment):
    agent = build_agent()

    result = agent.plan_response(detected_event(), assessment)

    assert result["metadata"]["planning_status"] == "skipped"
    assert result["metadata"]["reason"] == "risk_analysis_unavailable"


def test_skipped_plan_has_no_units_or_actions():
    """
    No generic fallback plan.

    A plausible default is indistinguishable from a real one at the API
    boundary, which is exactly why there isn't one.
    """
    agent = build_agent()

    assessment = successful_assessment()
    assessment["metadata"]["analysis_status"] = "failed"

    result = agent.plan_response(detected_event(), assessment)

    assert result["recommended_units"] == []
    assert result["response_actions"] == []
    assert result["plan_summary"] is None


# --------------------------------------------------------------------------
# Success path
# --------------------------------------------------------------------------


def test_successful_plan_is_returned():
    agent = build_agent()

    result = agent.plan_response(detected_event(), successful_assessment())

    assert result["metadata"]["planning_status"] == "success"
    assert result["recommended_units"] == ["fire_department", "police"]
    assert len(result["response_actions"]) == 2
    assert result["response_actions"][0]["timeframe"] == "immediate"


def test_plan_carries_verified_citations():
    agent = build_agent()

    result = agent.plan_response(detected_event(), successful_assessment())

    citations = result["grounding"]["citations"]

    assert len(citations) == 1
    assert citations[0]["verified"] is True
    assert citations[0]["source_url"] == "https://example.invalid/triage"


def test_agent_emits_rich_actions_not_flattened_strings():
    """
    Flattening to list[str] for the dashboard is ecoguard.api.main's job.

    Keeping one source of truth here means the transport shape can change
    without touching the agent.
    """
    agent = build_agent()

    result = agent.plan_response(detected_event(), successful_assessment())

    assert "response_plan" not in result
    assert isinstance(result["response_actions"][0], dict)


# --------------------------------------------------------------------------
# Degradation
# --------------------------------------------------------------------------


def test_missing_credentials_fails_before_retrieval():
    retriever = FakeRetriever()
    agent = build_agent(
        llm=FakeLLM(build_valid_plan(), available=False), retriever=retriever
    )

    result = agent.plan_response(detected_event(), successful_assessment())

    assert result["metadata"]["planning_status"] == "failed"
    assert result["error"] == "missing credentials"
    assert retriever.queries == []


def test_empty_retrieval_fails_before_the_model_call():
    llm = FakeLLM(build_valid_plan())
    agent = build_agent(llm=llm, retriever=FakeRetriever(chunks=[]))

    result = agent.plan_response(detected_event(), successful_assessment())

    assert result["metadata"]["planning_status"] == "failed"
    assert result["error"] == "no protocol match"
    assert llm.calls == []


@pytest.mark.parametrize("kind", ["timeout", "rate limited", "malformed response"])
def test_provider_errors_propagate_their_category(kind):
    agent = build_agent(llm=FakeLLM(ClaudeProviderError(kind)))

    result = agent.plan_response(detected_event(), successful_assessment())

    assert result["metadata"]["planning_status"] == "failed"
    assert result["error"] == kind


def test_ungrounded_plan_is_discarded():
    plan = build_valid_plan(
        protocol_citations=[
            {
                "chunk_id": "invented#chunk#0",
                "document_title": "Official Sounding Manual",
                "quoted_text": "All available units shall respond without delay.",
                "supports": "everything",
            }
        ]
    )
    agent = build_agent(llm=FakeLLM(plan))

    result = agent.plan_response(detected_event(), successful_assessment())

    assert result["metadata"]["planning_status"] == "failed"
    assert result["error"] == "ungrounded response"
    assert result["recommended_units"] == []


# --------------------------------------------------------------------------
# Schema coherence
# --------------------------------------------------------------------------


def test_action_assigned_to_an_unrecommended_unit_is_rejected_by_the_schema():
    """
    Caught at construction, so a fake cannot express an incoherent plan either.

    An action owned by a unit nobody dispatched leaves an operator with a task
    and no responder.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="unrecommended units"):
        build_valid_plan(
            recommended_units=["fire_department"],
            actions=[
                {
                    "action": "Request aerial water drops on the fire head.",
                    "responsible_unit": "aerial_firefighting",
                    "timeframe": "immediate",
                }
            ],
        )


def test_unknown_unit_id_is_rejected_by_the_schema():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        build_valid_plan(recommended_units=["space_force"])


# --------------------------------------------------------------------------
# Query construction
# --------------------------------------------------------------------------


def test_assessment_summary_renders_situational_context():
    llm = FakeLLM(build_valid_plan())
    agent = build_agent(llm=llm)

    assessment = successful_assessment(
        situational_context={
            "area_type": "urban_residential",
            "area_type_basis": "A town with residential roads and a hospital nearby.",
            "population_band": "10k_to_100k",
            "population_basis": "osm_population_tag",
            "evacuation_consideration": "localised_evacuation",
            "context_gaps": [],
        }
    )
    agent.plan_response(detected_event(), assessment)

    user_text = llm.calls[0]["user_text"]

    assert "urban_residential" in user_text
    assert "10k_to_100k" in user_text
    assert "osm_population_tag" in user_text


def test_assessment_summary_tolerates_a_missing_situational_context():
    """
    Guards replaying an assessment authored before this field existed.

    The evaluation harness feeds frozen assessments straight to the planner, so
    an older case file must not crash it.
    """
    agent = build_agent()

    assessment = successful_assessment()
    assessment.pop("situational_context", None)

    result = agent.plan_response(detected_event(), assessment)

    assert result["metadata"]["planning_status"] == "success"


def test_web_findings_are_flagged_as_weaker_evidence():
    """A looked-up fact must be visibly distinct from a collected one."""
    llm = FakeLLM(build_valid_plan())
    agent = build_agent(llm=llm)

    assessment = successful_assessment(
        web_findings=[
            {
                "query": "Yakir population",
                "fact": "Yakir had a population of 2,742 in 2024.",
                "source_url": "https://en.wikipedia.org/wiki/Yakir",
                "source_title": "Yakir — Wikipedia",
                "informs": "population_band",
            }
        ]
    )
    agent.plan_response(detected_event(), assessment)

    user_text = llm.calls[0]["user_text"]

    assert "looked up externally" in user_text
    assert "2,742" in user_text


@pytest.mark.parametrize(
    "area_type,expected_term",
    [
        ("urban_residential", "interior operations"),
        ("industrial", "interior operations"),
        ("wildland_urban_interface", "defensible space"),
        ("open_natural", "anchor point"),
    ],
)
def test_query_reflects_the_area_type(area_type, expected_term):
    """
    Area type steers the second retrieval to the right half of the corpus.

    A fire in a building needs the offensive/defensive doctrine; a fire in the
    open needs containment and triage. Retrieving the wrong half is how a plan
    ends up citing defensible space at an apartment fire.
    """
    retriever = FakeRetriever()
    agent = build_agent(retriever=retriever)

    assessment = successful_assessment(
        situational_context={
            "area_type": area_type,
            "area_type_basis": "x" * 25,
            "population_band": "1k_to_10k",
            "population_basis": "settlement_type_inference",
            "evacuation_consideration": "not_indicated",
            "context_gaps": [],
        }
    )
    agent.plan_response(detected_event(), assessment)

    assert expected_term in retriever.queries[0]


def test_query_targets_action_sections_not_classification():
    """
    The whole justification for a second model call.

    This query must reach for mobilisation and evacuation language, unlike the
    risk agent's query which reaches for danger classification.
    """
    retriever = FakeRetriever()
    agent = build_agent(retriever=retriever)

    agent.plan_response(detected_event(), successful_assessment())

    query = retriever.queries[0]

    assert "evacuation" in query
    assert "incident command" in query
    assert "resource allocation" in query


def test_query_includes_evacuation_terms_only_when_settlements_are_nearby():
    retriever = FakeRetriever()
    agent = build_agent(retriever=retriever)

    event = detected_event(
        geospatial_context={
            "nearby_settlements": [],
            "nearby_hospitals": [],
            "nearby_fire_stations": [{"name": "Station 1"}],
            "nearby_roads": [],
        }
    )
    agent.plan_response(event, successful_assessment())

    query = retriever.queries[0]

    assert "sheltering residents" not in query
    assert "mutual aid" not in query


def test_query_flags_absent_fire_stations_as_a_constraint():
    retriever = FakeRetriever()
    agent = build_agent(retriever=retriever)

    agent.plan_response(detected_event(), successful_assessment())

    assert "mutual aid extended response time" in retriever.queries[0]


def test_query_carries_the_risk_drivers_forward():
    """The second retrieval is aimed at what actually produced the score."""
    retriever = FakeRetriever()
    agent = build_agent(retriever=retriever)

    agent.plan_response(detected_event(), successful_assessment())

    assert "very high FWI class" in retriever.queries[0]


# --------------------------------------------------------------------------
# Prompt construction
# --------------------------------------------------------------------------


def test_prompt_presents_the_assessment_as_authoritative():
    llm = FakeLLM(build_valid_plan())
    agent = build_agent(llm=llm)

    agent.plan_response(detected_event(), successful_assessment())

    user_text = llm.calls[0]["user_text"]

    assert "do not re-score" in user_text.lower()
    assert "Risk score: 78" in user_text
    assert "Risk level: high" in user_text


def test_prompt_caches_the_stable_prefix_only():
    llm = FakeLLM(build_valid_plan())
    agent = build_agent(llm=llm)

    agent.plan_response(detected_event(), successful_assessment())

    call = llm.calls[0]

    assert call["system_blocks"][0]["cache_control"] == {"type": "ephemeral"}
    assert CHUNK["chunk_id"] not in call["system_blocks"][0]["text"]
    assert CHUNK["chunk_id"] in call["user_text"]


def test_planning_and_risk_prompts_are_different():
    """
    Two distinct system prompts mean two independent cache entries.

    If these ever converged, the argument for two calls would collapse.
    """
    from ecoguard.response_planner.fire.planning_agent import PLANNING_SYSTEM_PROMPT
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import RISK_SYSTEM_PROMPT

    assert PLANNING_SYSTEM_PROMPT != RISK_SYSTEM_PROMPT


# --------------------------------------------------------------------------
# Boundary contract
# --------------------------------------------------------------------------


def test_result_is_plain_json_serialisable():
    agent = build_agent()

    json.dumps(agent.plan_response(detected_event(), successful_assessment()))
    json.dumps(agent.plan_response(detected_event(), {}))


# --------------------------------------------------------------------------
# Handoff contract for a downstream resource allocation agent
# --------------------------------------------------------------------------


def test_plan_stands_alone_as_a_handoff():
    """
    A plan must be meaningful without the event that produced it.

    A resource allocation agent may receive only the plan. If it cannot tell
    which fire the plan is for, or how severe that fire was judged, the plan is
    unusable on its own and only works when it happens to arrive in the same
    payload as the event. "Arrived together" is not a contract.
    """
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_event_id

    agent = build_agent()
    event = detected_event()

    plan = agent.plan_response(event, successful_assessment())

    assert plan["event_id"] == build_event_id(event)
    assert plan["event_type"] == "fire"
    assert plan["location"] == {"latitude": 31.9, "longitude": 34.8}


def test_plan_records_the_risk_it_is_responding_to():
    """
    The plan carries the assessment that justified it, semantics included.

    Without risk_semantics a downstream agent cannot tell whether the 78 it is
    reading is a 0-100 severity or something else entirely.
    """
    agent = build_agent()

    plan = agent.plan_response(detected_event(), successful_assessment())

    assert plan["responding_to"]["risk_score"] == 78
    assert plan["responding_to"]["risk_level"] == "high"
    assert plan["responding_to"]["risk_semantics"] == "detected_event_operational_risk"


def test_skipped_plan_still_identifies_its_event():
    """
    An empty plan names what it declined to plan for.

    Otherwise a consumer receives an anonymous empty object and cannot tell
    which event has no plan.
    """
    agent = build_agent()
    event = detected_event()

    assessment = successful_assessment()
    assessment["metadata"]["analysis_status"] = "failed"

    plan = agent.plan_response(event, assessment)

    assert plan["metadata"]["planning_status"] == "skipped"
    assert plan["event_id"] is not None
    assert plan["responding_to"]["risk_score"] is None


def test_failed_plan_still_identifies_its_event():
    agent = build_agent(llm=FakeLLM(ClaudeProviderError("timeout")))
    event = detected_event()

    plan = agent.plan_response(event, successful_assessment())

    assert plan["metadata"]["planning_status"] == "failed"
    assert plan["event_id"] is not None


def test_plan_with_no_event_context_does_not_raise():
    """Defensive: an unknown event yields a null id rather than an exception."""
    agent = build_agent()

    plan = agent.plan_response({}, {})

    assert plan["metadata"]["planning_status"] == "skipped"
    assert plan["event_id"] is None
