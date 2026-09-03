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

from agents.response_planning_agent import ResponsePlanningAgent
from agents.risk_analysis_schemas import ResponsePlan
from services.claude_llm_service import ClaudeProviderError

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
        "event_type": "fire",
        "location": {"latitude": 31.9, "longitude": 34.8},
        "risk_score": 78,
        "risk_level": "high",
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
    Flattening to list[str] for the dashboard is backend.main's job.

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
    from agents.response_planning_agent import PLANNING_SYSTEM_PROMPT
    from agents.risk_analysis_agent import RISK_SYSTEM_PROMPT

    assert PLANNING_SYSTEM_PROMPT != RISK_SYSTEM_PROMPT


# --------------------------------------------------------------------------
# Boundary contract
# --------------------------------------------------------------------------


def test_result_is_plain_json_serialisable():
    agent = build_agent()

    json.dumps(agent.plan_response(detected_event(), successful_assessment()))
    json.dumps(agent.plan_response(detected_event(), {}))
