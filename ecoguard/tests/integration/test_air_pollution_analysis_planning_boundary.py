"""Test-only composition across the external Coordinator/analyzer/planner boundary."""

from unittest.mock import Mock

import pytest

from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import (
    AirPollutionTrendPrediction,
    AnalysisComponent,
)
from ecoguard.analyzers.non_emergency.air_pollution.event_analyzer import (
    AirPollutionNonEmergencyAnalyzer,
)
from ecoguard.analyzers.non_emergency.air_pollution.population_analysis import (
    AirPollutionPopulationAnalysisService,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_schemas import (
    TransportEvidenceReference,
)
from ecoguard.detectors.air_pollution.correlation import PollutionCorrelationCandidate
from ecoguard.response_planner.air_pollution.planner import AirPollutionResponsePlanner
from ecoguard.tests.analyzers.non_emergency.air_pollution.test_event_analyzer import (
    GENERATED_AT,
    OBSERVED_AT,
    _analysis_input,
    _candidate,
    _index_lookup,
    _transport_service,
)
from ecoguard.tests.response_planner.air_pollution.test_planner import (
    CHUNK,
    _planner,
    _proposal,
)


def _candidate_for(pollutant: str) -> PollutionCorrelationCandidate:
    payload = _candidate().model_dump(round_trip=True)
    payload["anomaly"]["detection_id"] = f"air-pollution:{pollutant.lower()}:test"
    payload["anomaly"]["pollutant"] = pollutant
    payload["anomaly"]["live_observation"]["pollutant"] = pollutant
    payload["anomaly"]["baseline_evidence"]["identity"]["pollutant"] = pollutant
    return PollutionCorrelationCandidate.model_validate(payload)


def _trend_available(pollutant: str) -> AnalysisComponent[AirPollutionTrendPrediction]:
    return AnalysisComponent[AirPollutionTrendPrediction](
        status="success",
        result=AirPollutionTrendPrediction(
            trend="RISING",
            confidence=0.7,
            probabilities={"FALLING": 0.1, "STABLE": 0.2, "RISING": 0.7},
            pollutant=pollutant,
            station_id="42",
            channel_id="7001",
            unit="ppb",
            issued_at=GENERATED_AT,
            as_of=OBSERVED_AT,
            model_version="synthetic-boundary-test-v1",
            artifact_version="synthetic-boundary-artifact-v1",
            feature_policy_version="test-features-v1",
            preprocessing_version="test-preprocessing-v1",
            epsilon_policy_version="test-epsilon-v1",
        ),
        evidence=[
            TransportEvidenceReference(
                evidence_id=f"trend-ml:{pollutant.lower()}:synthetic",
                source_name="synthetic injected trend service",
                source_type="sgd_logistic_trend_model",
            )
        ],
    )


def _trend_unavailable(reason: str) -> AnalysisComponent[AirPollutionTrendPrediction]:
    return AnalysisComponent[AirPollutionTrendPrediction](
        status="unavailable",
        unavailable_reason=reason,
    )


def _compose_analysis(*, pollutant: str, trend_component):
    candidate = _candidate_for(pollutant)
    coordinator_input = _analysis_input(candidate)

    trend_service = Mock()
    trend_service.predict.return_value = trend_component

    index_client = Mock()
    index_client.get_station_index_evidence.return_value = _index_lookup(
        pollutant=pollutant,
        driving_pollutant=pollutant,
        evidence_id=f"ministry-aqi:42:7001:{pollutant}:test",
    )

    population_query = Mock(
        return_value={
            "grid_available": True,
            "intersected_cell_count": 7,
            "weighted_population": 123.6,
        }
    )
    population_service = AirPollutionPopulationAnalysisService(population_query)
    transport_service, wind_provider = _transport_service()

    analysis = AirPollutionNonEmergencyAnalyzer(
        transport_service=transport_service,
        ministry_index_client=index_client,
        population_service=population_service,
        trend_inference_service=trend_service,
        clock=lambda: GENERATED_AT,
    ).analyze(coordinator_input)

    return (
        coordinator_input,
        analysis,
        trend_service,
        index_client,
        wind_provider,
        population_query,
    )


def _plan(analysis, *, pollutant: str, evidence_ids: list[str]):
    proposal = _proposal()
    proposal.actions[0].supporting_analysis_evidence_ids = evidence_ids
    planner, llm, retriever = _planner(output=proposal)
    retriever.documents[CHUNK["document_id"]]["supported_pollutants"] = [pollutant]
    result = planner.plan_response(analysis)
    return result, llm


def test_coordinator_shaped_input_composes_trend_and_grounded_plan():
    trend = _trend_available("NO2")
    coordinator_input, analysis, trend_service, index_client, wind, population = (
        _compose_analysis(pollutant="NO2", trend_component=trend)
    )
    trend_evidence_id = trend.evidence[0].evidence_id

    result, llm = _plan(
        analysis,
        pollutant="NO2",
        evidence_ids=["coordinator-evidence-1", trend_evidence_id],
    )

    assert coordinator_input.coordinator_routing_id == "routing-external-1"
    assert coordinator_input.routing.route == "non_emergency"
    trend_service.predict.assert_called_once_with(
        coordinator_input.current_state.result.detections[0]
    )
    index_client.get_station_index_evidence.assert_called_once()
    wind.select_wind_evidence.assert_called_once()
    population.assert_called_once()
    assert analysis.status == "partial"
    assert analysis.future_prediction.result.trend == "RISING"
    assert analysis.severity_assessment.result is not None
    assert analysis.transport_analysis.result is not None
    assert analysis.population_impact.result.total_relevant_population == 124
    assert result.plan.status == "success"
    assert trend_evidence_id in result.plan.analysis_evidence_references
    assert trend_evidence_id in llm.calls[0]["user_text"]


@pytest.mark.parametrize(
    ("pollutant", "unavailable_reason"),
    [
        ("NO2", "insufficient_causal_history"),
        ("PM10", "pm10_no_accepted_model"),
    ],
)
def test_unavailable_trend_does_not_block_other_components_or_planning(
    pollutant: str, unavailable_reason: str
):
    coordinator_input, analysis, trend_service, index_client, wind, population = (
        _compose_analysis(
            pollutant=pollutant,
            trend_component=_trend_unavailable(unavailable_reason),
        )
    )

    result, llm = _plan(
        analysis,
        pollutant=pollutant,
        evidence_ids=["coordinator-evidence-1"],
    )

    trend_service.predict.assert_called_once_with(
        coordinator_input.current_state.result.detections[0]
    )
    index_client.get_station_index_evidence.assert_called_once()
    wind.select_wind_evidence.assert_called_once()
    population.assert_called_once()
    assert analysis.status == "partial"
    assert analysis.future_prediction.status == "unavailable"
    assert analysis.future_prediction.unavailable_reason == unavailable_reason
    assert analysis.severity_assessment.result is not None
    assert analysis.transport_analysis.result is not None
    assert analysis.population_impact.result.total_relevant_population == 124
    assert result.plan.status == "success"
    assert any(
        unavailable_reason in gap for gap in result.plan.evidence_gaps
    )
    assert unavailable_reason in llm.calls[0]["user_text"]
