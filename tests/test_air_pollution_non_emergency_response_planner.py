from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from agents.air_pollution_event_analyzer import AirPollutionNonEmergencyAnalyzer
from agents.air_pollution_response_planner import AirPollutionResponsePlanner
from agents.air_pollution_response_schemas import (
    AirPollutionPlanProposal,
    AirPollutionResponsePlan,
)
from services.claude_llm_service import ClaudeProviderError
from services.protocol_retrieval_service import ProtocolRetriever
from test_air_pollution_non_emergency_analyzer import (
    GENERATED_AT,
    _analysis_input,
    _transport_service,
)

GUIDANCE = "Use official air-quality monitoring information and follow Ministry of Environmental Protection public updates."
CHUNK = {
    "chunk_id": "israel-air-monitoring#monitoring-and-public-information#0",
    "document_id": "israel-air-monitoring",
    "document_title": "Israel: air monitoring and public information responsibilities",
    "source_url": "https://www.gov.il/he/departments/Units/asbestos_department",
    "heading_path": "Monitoring and public information",
    "text": GUIDANCE,
}
REVIEWED_ACTION = {
    "recommendation": GUIDANCE,
    "responsible_authority_type": "environmental_protection_authority",
    "resource_type": "air_quality_monitoring",
    "timeframe": "not_specified",
    "priority": "not_specified",
}


class FakeRetriever:
    hazard = "air_pollution"

    def __init__(self, *, chunks=None):
        self.chunks = [CHUNK] if chunks is None else chunks
        self.documents = {
            "israel-air-monitoring": {
                "supported_pollutants": ["NO2"],
                "reviewed_actions": [REVIEWED_ACTION],
            }
        }
        self.queries = []

    def retrieve(self, query, top_k):
        self.queries.append((query, top_k))
        return list(self.chunks)


class FakeLLM:
    available = True

    def __init__(self, output):
        self.output = output
        self.calls = []

    def parse_structured(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def _analysis(*, with_transport=True):
    if with_transport:
        service, wind_provider = _transport_service()
    else:
        service, wind_provider = None, None
    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=service,
        clock=lambda: GENERATED_AT,
    ).analyze(_analysis_input())
    return report, wind_provider


def _proposal(**changes):
    values = {
        "summary": "Grounded non-emergency monitoring recommendation.",
        "recommended_authority_types": ["environmental_protection_authority"],
        "recommended_resource_types": ["air_quality_monitoring"],
        "actions": [
            {
                **REVIEWED_ACTION,
                "rationale": "The Analyzer retains a statistically unusual Ministry monitoring observation.",
                "supporting_chunk_ids": [CHUNK["chunk_id"]],
                "supporting_analysis_evidence_ids": ["coordinator-evidence-1"],
                "spatial_relevance": "The recommendation remains general; nearby places do not establish exposure.",
            }
        ],
        "assumptions": [],
        "evidence_gaps": [
            "Event severity, trend, and population impact are unavailable."
        ],
        "limitations": ["No exposure or affected population is confirmed."],
        "protocol_citations": [
            {
                "chunk_id": CHUNK["chunk_id"],
                "document_title": CHUNK["document_title"],
                "quoted_text": GUIDANCE,
                "supports": "Official monitoring and public updates recommendation.",
            }
        ],
    }
    values.update(changes)
    return AirPollutionPlanProposal(**values)


def _planner(*, output=None, chunks=None):
    llm = FakeLLM(output or _proposal())
    retriever = FakeRetriever(chunks=chunks)
    return AirPollutionResponsePlanner(llm_service=llm, retriever=retriever), llm, retriever


def test_analysis_is_consumed_and_preserved_with_grounded_non_emergency_action():
    analysis, _ = _analysis()
    planner, _, _ = _planner()

    result = planner.plan_response(analysis)

    assert result.analysis == analysis
    assert result.plan.status == "success"
    action = result.plan.actions[0]
    assert action.recommendation == GUIDANCE
    assert action.resource_type == "air_quality_monitoring"
    assert action.responsible_authority_type == "environmental_protection_authority"
    assert result.plan.analysis_evidence_references == ["coordinator-evidence-1"]


def test_no_emergency_resource_or_dispatch_contract_exists():
    plan = _planner()[0].plan_response(_analysis()[0]).plan

    assert not {"police", "ambulance", "fire_truck", "dispatch"} & set(
        plan.recommended_resource_types
    )
    assert not {
        "allocated_resources",
        "resource_quantities",
        "dispatch",
        "emergency_classification",
    } & plan.model_dump().keys()
    for forbidden in ("dispatch", "ambulances", "fire_trucks", "police_units"):
        with pytest.raises(ValidationError):
            AirPollutionResponsePlan.model_validate(
                {"status": "failed", "reason": "guidance_unavailable", forbidden: []}
            )


def test_protocol_citation_and_reviewed_action_are_verified():
    plan = _planner()[0].plan_response(_analysis()[0]).plan

    assert plan.protocol_references[0].verified is True
    assert plan.protocol_references[0].chunk_id == CHUNK["chunk_id"]
    assert plan.protocol_references[0].quoted_text == GUIDANCE
    assert plan.actions[0].supporting_chunk_ids == [CHUNK["chunk_id"]]


def test_real_protocol_corpus_loads_reviewed_non_emergency_categories():
    retriever = ProtocolRetriever(hazard="air_pollution")

    assert retriever.available
    reviewed = [
        action
        for document in retriever.documents.values()
        for action in document.get("reviewed_actions", [])
    ]
    assert reviewed
    assert {item["resource_type"] for item in reviewed} <= {
        "air_quality_monitoring",
        "public_health_advisory",
        "public_information",
        "environmental_inspection",
        "laboratory_analysis",
    }
    assert not {"police", "ambulance", "fire_truck", "dispatch"} & {
        item["resource_type"] for item in reviewed
    }


def test_missing_severity_trend_and_population_are_preserved_as_unknown():
    analysis, _ = _analysis(with_transport=False)
    result = _planner()[0].plan_response(analysis)

    assert result.plan.status == "success"
    assert result.analysis.severity_assessment.status == "unavailable"
    assert result.analysis.future_prediction.status == "unavailable"
    assert result.analysis.population_impact.status == "unavailable"
    assert result.analysis.population_impact.result is None
    text = " ".join(result.plan.limitations)
    assert "Event-level severity is unavailable" in text
    assert "Future trend is unavailable" in text
    assert "Population impact is unavailable" in text
    assert "population" not in result.plan.model_dump_json().lower() or "unavailable" in text


def test_transport_spatial_evidence_may_be_referenced_without_recalculation():
    analysis, wind_provider = _analysis()
    wind_provider.select_wind_evidence.reset_mock()
    result = _planner()[0].plan_response(analysis)

    wind_provider.select_wind_evidence.assert_not_called()
    assert result.analysis.transport_analysis.result.spatial_output.corridor_polygon
    assert result.plan.actions[0].spatial_relevance is not None
    assert "does not confirm exposure" in (
        result.plan.actions[0].spatial_relevance.lower()
    )


def test_analyzer_scientific_limitations_are_preserved():
    analysis, _ = _analysis()
    plan = _planner()[0].plan_response(analysis).plan

    for limitation in analysis.limitations:
        assert limitation in plan.limitations
    assert any("not proof" in item.lower() for item in plan.limitations)


def test_unknown_or_unverified_evidence_reference_fails_closed():
    proposal = _proposal()
    proposal.actions[0].supporting_analysis_evidence_ids = ["invented-evidence"]

    result = _planner(output=proposal)[0].plan_response(_analysis()[0])

    assert result.plan.status == "failed"
    assert result.plan.reason == "ungrounded_response"
    assert result.plan.actions == []


def test_missing_guidance_or_model_failure_is_safe():
    analysis, _ = _analysis()
    no_guidance = _planner(chunks=[])[0].plan_response(analysis)
    failed_model = _planner(output=ClaudeProviderError("provider failure"))[0].plan_response(
        analysis
    )

    assert no_guidance.plan.reason == "guidance_unavailable"
    assert failed_model.plan.reason == "model_failure"
    assert not no_guidance.plan.actions and not failed_model.plan.actions


def test_planner_has_no_runtime_store_scheduler_database_or_implementor_dependency():
    import agents.air_pollution_response_planner as planner_module

    names = set(planner_module.__dict__)
    assert not {
        "AirPollutionRuntimeService",
        "InMemoryAirPollutionEventStore",
        "Scheduler",
        "Session",
        "ResponseImplementor",
    } & names


def test_planner_does_not_repeat_detector_or_analyzer_science():
    analysis, wind_provider = _analysis()
    wind_provider.select_wind_evidence.reset_mock()
    planner, llm, _ = _planner()

    result = planner.plan_response(analysis)

    wind_provider.select_wind_evidence.assert_not_called()
    assert result.analysis.current_state == analysis.current_state
    assert result.analysis.transport_analysis == analysis.transport_analysis
    prompt = llm.calls[0]["user_text"]
    assert analysis.current_state.result.detections[0].anomaly.detector_rule_version in prompt
    assert "ministry_air_quality_index_service_unavailable" in prompt
    assert "trend_prediction_not_implemented" in prompt
    assert "shared_population_service_unavailable" in prompt
