"""Offline EA-312 tests with injected guidance and model output."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agents.air_pollution_anomaly_schemas import AirPollutionAnomaly
from agents.air_pollution_correlation import compare_pollution_candidates, correlation_candidate
from agents.air_pollution_response_planner import AirPollutionResponsePlanner
from agents.air_pollution_response_schemas import (
    AirPollutionPlanProposal, AirPollutionResponsePlan,
)
from agents.air_pollution_spatial_schemas import SpatiallyEnrichedAirPollutionAnomaly
from services.claude_llm_service import ClaudeProviderError

NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
GUIDANCE_TEXT = (
    "Continue reviewing measurements and publish authoritative updates."
)
CHUNK = {
    "chunk_id": "official-guidance#public-information#0",
    "document_id": "official-guidance", "document_title": "Official pollution guidance",
    "source_url": "https://example.invalid/test-guidance", "heading_path": "Public information",
    "text": GUIDANCE_TEXT,
}


class FakeRetriever:
    hazard = "air_pollution"

    def __init__(self, chunks=None, available=True):
        self.chunks = [CHUNK] if chunks is None else chunks
        self.available = available
        self.queries = []
        self.documents = {CHUNK["document_id"]: {
            "supported_pollutants": ["PM2.5", "PM10"],
            "reviewed_actions": [{
                "recommendation": GUIDANCE_TEXT,
                "responsible_authority_type": "environmental_protection_authority",
                "resource_type": "air_quality_monitoring", "timeframe": "ongoing",
                "priority": "monitoring",
            }],
        }}

    def retrieve(self, query, top_k=5):
        self.queries.append(query)
        return self.chunks[:top_k]


class FakeLLM:
    model = "test-model"

    def __init__(self, output, available=True):
        self.output = output
        self.available = available
        self.calls = []

    def parse_structured(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def anomaly(identifier="event-1", pollutant=True):
    return AirPollutionAnomaly(
        detection_id=identifier, observed_at=NOW, detected_at=NOW,
        location={"latitude": 32.1, "longitude": 34.8},
        pollutant_observations=([{
            "pollutant": "PM2.5", "value": 42.0, "unit": "µg/m³",
            "source_id": "ministry-station-1",
        }] if pollutant else []), severity="medium", confidence=0.64,
        explanation="Sustained anomaly from normalized preliminary observations",
        anomaly_reasons=["sustained PM2.5 elevation"],
        sources=[{
            "source_id": "ministry", "source_name": "National monitoring network",
            "metadata": {"station_id": "station-1", "channel_id": "channel-7"},
        }],
    )


def proposal(**overrides):
    payload = {
        "summary": "Continue authoritative monitoring and prepare grounded public information.",
        "recommended_authority_types": ["environmental_protection_authority"],
        "recommended_resource_types": ["air_quality_monitoring"],
        "actions": [{
            "recommendation": "Continue reviewing measurements and publish authoritative updates.",
            "responsible_authority_type": "environmental_protection_authority",
            "resource_type": "air_quality_monitoring", "timeframe": "ongoing",
            "priority": "monitoring", "supporting_chunk_ids": [CHUNK["chunk_id"]],
        }],
        "assumptions": ["The preliminary observations remain representative."],
        "evidence_gaps": ["No source attribution is available."],
        "limitations": ["This recommendation does not confirm public exposure."],
        "protocol_citations": [{
            "chunk_id": CHUNK["chunk_id"], "document_title": "Ignored model title",
            "quoted_text": GUIDANCE_TEXT, "supports": "Monitoring and public updates",
        }],
    }
    payload.update(overrides)
    return AirPollutionPlanProposal.model_validate(payload)


def planner(output=None, chunks=None, available=True):
    llm = FakeLLM(output or proposal(), available=available)
    retriever = FakeRetriever(chunks=chunks)
    return AirPollutionResponsePlanner(llm_service=llm, retriever=retriever), llm, retriever


def test_successful_grounded_plan_preserves_types_actions_and_citation():
    agent, llm, _ = planner()
    result = agent.plan_response(anomaly())
    assert result.plan.status == "success"
    assert result.plan.recommended_authority_types == ["environmental_protection_authority"]
    assert result.plan.recommended_resource_types == ["air_quality_monitoring"]
    assert result.plan.actions[0].timeframe == "ongoing"
    assert result.plan.protocol_references[0].source_url == CHUNK["source_url"]
    assert result.plan.protocol_references[0].verified is True
    assert llm.calls[0]["output_format"] is AirPollutionPlanProposal


def test_partial_spatial_context_and_no_correlation_are_explicit():
    enriched = SpatiallyEnrichedAirPollutionAnomaly(
        anomaly=anomaly(), spatial_context={
            "location": {"latitude": 32.1, "longitude": 34.8},
            "lookup_radius_km": 2.0, "status": "partial", "source": "OSM",
            "nearby_settlements": [{"name": "Nearby place"}],
        },
    )
    result = planner()[0].plan_response(enriched)
    assert result.event.spatial_context.nearby_settlements[0].name == "Nearby place"
    assert any("partial" in item for item in result.plan.limitations)
    assert any("No correlation" in item for item in result.plan.limitations)


def test_matching_correlation_evidence_is_preserved():
    left, right = correlation_candidate(anomaly()), correlation_candidate(anomaly("event-2"))
    evidence = compare_pollution_candidates(left, right)
    result = planner()[0].plan_response(left, correlation_evidence=evidence)
    assert result.plan.status == "success"
    assert result.correlation_evidence == evidence


def test_mismatched_correlation_evidence_fails_without_erasing_event():
    left, right = correlation_candidate(anomaly()), correlation_candidate(anomaly("event-2"))
    evidence = compare_pollution_candidates(left, right)
    third = correlation_candidate(anomaly("event-3"))
    result = planner()[0].plan_response(third, correlation_evidence=evidence)
    assert result.plan.reason == "correlation_context_mismatch"
    assert result.event == third


def test_missing_guidance_fails_before_model_call():
    agent, llm, _ = planner(chunks=[])
    result = agent.plan_response(anomaly())
    assert result.plan.status == "failed" and result.plan.reason == "guidance_unavailable"
    assert llm.calls == [] and result.event.anomaly == anomaly()


def test_guidance_retrieval_failure_is_sanitized():
    agent, llm, retriever = planner()
    retriever.retrieve = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("provider URL with sensitive query data")
    )
    result = agent.plan_response(anomaly())
    assert result.plan.reason == "guidance_unavailable"
    assert "sensitive" not in result.model_dump_json()
    assert not llm.calls


def test_wrong_hazard_corpus_is_rejected():
    agent, llm, retriever = planner()
    retriever.hazard = "fire"
    result = agent.plan_response(anomaly())
    assert result.plan.reason == "guidance_scope_mismatch"
    assert not llm.calls and not retriever.queries


def test_insufficient_evidence_is_skipped_before_guidance_or_model():
    agent, llm, retriever = planner()
    result = agent.plan_response(anomaly(pollutant=False))
    assert result.plan.status == "skipped"
    assert result.plan.reason == "insufficient_anomaly_evidence"
    assert not llm.calls and not retriever.queries


def test_model_unavailable_and_provider_failure_are_safe():
    unavailable, _, _ = planner(available=False)
    assert unavailable.plan_response(anomaly()).plan.reason == "model_unavailable"
    failed, _, _ = planner(output=ClaudeProviderError("provider error"))
    result = failed.plan_response(anomaly())
    assert result.plan.reason == "model_failure" and result.plan.actions == []


def test_malformed_output_is_rejected():
    agent, llm, _ = planner()
    llm.output = {"plausible": "but not schema validated"}
    assert agent.plan_response(anomaly()).plan.reason == "malformed_output"


def test_unverifiable_citation_rejects_whole_plan():
    bad = proposal(protocol_citations=[{
        "chunk_id": CHUNK["chunk_id"], "document_title": "Bad",
        "quoted_text": "This unsupported recommendation was never in the retrieved source.",
        "supports": "Unsupported action",
    }])
    result = planner(output=bad)[0].plan_response(anomaly())
    assert result.plan.reason == "ungrounded_response"
    assert result.plan.actions == [] and result.plan.protocol_references == []


def test_action_with_unverified_support_id_rejects_whole_plan():
    actions = [proposal().actions[0].model_copy(update={"supporting_chunk_ids": ["invented"]})]
    result = planner(output=proposal(actions=actions))[0].plan_response(anomaly())
    assert result.plan.reason == "ungrounded_response"


def test_provenance_and_original_anomaly_survive_planning_failure():
    original = anomaly()
    result = planner(chunks=[])[0].plan_response(original)
    assert result.event.anomaly == original
    assert result.event.station_channels == [("ministry", "station-1", "channel-7")]
    assert result.event.anomaly.pollutant_observations[0].source_id == "ministry-station-1"


@pytest.mark.parametrize("field", ["dispatch", "availability", "allocated_resources", "resource_quantity"])
def test_operational_fields_are_not_part_of_plan_contract(field):
    with pytest.raises(ValidationError):
        AirPollutionResponsePlan.model_validate({
            "status": "failed", "reason": "guidance_unavailable", field: True,
        })


def test_action_requires_declared_authority_and_resource_types():
    with pytest.raises(ValidationError):
        proposal(recommended_authority_types=["public_health_authority"])
    with pytest.raises(ValidationError):
        proposal(recommended_resource_types=["public_information"])


def test_missing_corpus_does_not_call_claude(tmp_path):
    from services.protocol_retrieval_service import ProtocolRetriever

    agent = AirPollutionResponsePlanner(
        llm_service=FakeLLM(proposal()),
        retriever=ProtocolRetriever(hazard="air_pollution", corpus_path=tmp_path / "absent"),
    )
    result = agent.plan_response(anomaly())
    assert result.plan.reason == "guidance_unavailable"
    assert agent.llm_service.calls == []


def test_fire_coordinator_and_resource_allocation_are_not_called(monkeypatch):
    from agents.coordinator import FireCoordinator
    from agents.resource_allocation_agent import ResourceAllocationAgent

    monkeypatch.setattr(FireCoordinator, "run_event_pipeline", lambda *args, **kwargs: pytest.fail("fire called"))
    monkeypatch.setattr(ResourceAllocationAgent, "allocate_resources", lambda *args, **kwargs: pytest.fail("allocation called"))
    assert planner()[0].plan_response(anomaly()).plan.status == "success"
