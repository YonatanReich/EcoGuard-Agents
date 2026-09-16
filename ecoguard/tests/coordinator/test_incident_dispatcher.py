"""Shared incident dispatch and Air Pollution production-handler tests."""

from unittest.mock import Mock

from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import (
    AirPollutionTrendPrediction,
    AnalysisComponent,
)
from ecoguard.analyzers.non_emergency.air_pollution.event_analyzer import (
    AirPollutionNonEmergencyAnalyzer,
)
from ecoguard.analyzers.non_emergency.air_pollution.incident_handler import (
    AirPollutionIncidentHandler,
)
from ecoguard.analyzers.non_emergency.air_pollution.population_analysis import (
    AirPollutionPopulationAnalysisService,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_schemas import (
    TransportEvidenceReference,
)
from ecoguard.coordinator.agent import CoordinationResult
from ecoguard.coordinator.dispatcher import dispatch_incidents, dispatch_touched
from ecoguard.coordinator.incidents import signal_as_json
from ecoguard.detectors.air_pollution.cell_signal_adapter import (
    air_pollution_candidate_to_cell_signal,
)
from ecoguard.response_planner.air_pollution.schemas import AirPollutionPlanningResult
from ecoguard.shared.signals import FIRE, HIGH, CellSignal
from ecoguard.tests.analyzers.non_emergency.air_pollution.test_event_analyzer import (
    GENERATED_AT,
    OBSERVED_AT,
    _candidate,
    _index_lookup,
    _transport_service,
)
from ecoguard.tests.response_planner.air_pollution.test_planner import (
    CHUNK,
    _planner,
    _proposal,
)

REQUESTED_AT = GENERATED_AT


def _incident(*, identifier="INC-AP-1", hybrid=False):
    candidate = _candidate()
    pollution = signal_as_json(air_pollution_candidate_to_cell_signal(candidate))
    signals = [pollution]
    hazards = ["air_pollution"]
    queues = ["non_emergency"]
    primary = "air_pollution"
    if hybrid:
        fire = CellSignal(
            cell_id=pollution["cell_id"],
            observed_at=OBSERVED_AT,
            hazard=FIRE,
            variable="frp",
            value=25.0,
            unit="MW",
            source="firms",
            rarity=1.0,
            direction=HIGH,
        )
        signals.insert(0, signal_as_json(fire))
        hazards.insert(0, FIRE)
        queues.insert(0, "emergency")
        primary = FIRE
    return {
        "id": identifier,
        "status": "open",
        "primary_hazard": primary,
        "hazards": hazards,
        "queues": queues,
        "signals": signals,
        "first_seen_at": OBSERVED_AT,
        "last_signal_at": OBSERVED_AT,
    }, candidate


def _working_handler(*, trend_component=None):
    candidate = _candidate()
    trend_component = trend_component or AnalysisComponent[AirPollutionTrendPrediction](
        status="success",
        result=AirPollutionTrendPrediction(
            trend="RISING",
            confidence=0.7,
            probabilities={"FALLING": 0.1, "STABLE": 0.2, "RISING": 0.7},
            pollutant=candidate.anomaly.pollutant,
            station_id=candidate.anomaly.station_id,
            channel_id=candidate.anomaly.channel_id,
            unit=candidate.anomaly.unit,
            issued_at=GENERATED_AT,
            as_of=OBSERVED_AT,
            model_version="dispatcher-test-v1",
            artifact_version="dispatcher-artifact-v1",
            feature_policy_version="features-v1",
            preprocessing_version="preprocessing-v1",
            epsilon_policy_version="epsilon-v1",
        ),
        evidence=[TransportEvidenceReference(
            evidence_id="trend:dispatcher-test",
            source_name="injected trend service",
        )],
    )
    trend = Mock()
    trend.predict.return_value = trend_component
    index = Mock()
    index.get_station_index_evidence.return_value = _index_lookup()
    population = AirPollutionPopulationAnalysisService(Mock(return_value={
        "grid_available": True,
        "intersected_cell_count": 2,
        "weighted_population": 50.0,
    }))
    transport, _ = _transport_service()
    analyzer = AirPollutionNonEmergencyAnalyzer(
        transport_service=transport,
        ministry_index_client=index,
        population_service=population,
        trend_inference_service=trend,
        clock=lambda: GENERATED_AT,
    )

    proposal = _proposal()
    proposal.actions[0].supporting_analysis_evidence_ids = [
        candidate.anomaly.detection_id,
        *[item.evidence_id for item in trend_component.evidence],
    ]
    planner, _, retriever = _planner(output=proposal)
    retriever.documents[CHUNK["document_id"]]["supported_pollutants"] = [
        candidate.anomaly.pollutant
    ]
    return AirPollutionIncidentHandler(
        analyzer=analyzer,
        planner=planner,
        clock=lambda: GENERATED_AT,
    ), trend


def test_persisted_incident_runs_existing_analyzer_and_planner():
    incident, candidate = _incident()
    handler, trend = _working_handler()
    stored_signal = incident["signals"][0]

    assert stored_signal["rarity"] is None
    assert stored_signal["severity"] is None
    assert stored_signal["confidence"] is None

    results = dispatch_incidents(
        [incident],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )

    assert len(results) == 1
    result = results[0]
    assert result.hazard == "air_pollution"
    assert result.route == "non_emergency"
    assert result.status == "partial"
    assert result.analysis_status == "partial"
    assert result.planner_status == "success"
    assert isinstance(result.planner_result, AirPollutionPlanningResult)
    analysis = result.analysis_result
    assert analysis.incident_id == incident["id"]
    assert analysis.analysis_id == result.analysis_id
    assert analysis.coordinator_routing_id == result.coordinator_routing_id
    assert analysis.routing.route == "non_emergency"
    assert analysis.routing.routed_by == "shared_coordinator"
    assert analysis.requested_at == REQUESTED_AT
    restored = analysis.current_state.result.detections[0]
    assert restored == candidate
    assert restored.anomaly.baseline_evidence.statistics.p95 == 20.0
    assert analysis.severity_assessment.result.ecoguard_severity_level is None
    trend.predict.assert_called_once_with(restored)


def test_unavailable_trend_is_graceful():
    unavailable = AnalysisComponent[AirPollutionTrendPrediction](
        status="unavailable",
        unavailable_reason="pm10_no_accepted_model",
    )
    incident, _ = _incident()
    handler, trend = _working_handler(trend_component=unavailable)

    result = dispatch_incidents(
        [incident],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )[0]

    assert result.status == "partial"
    assert result.analysis_result.future_prediction.status == "unavailable"
    assert (
        result.analysis_result.future_prediction.unavailable_reason
        == "pm10_no_accepted_model"
    )
    assert result.planner_status == "success"
    trend.predict.assert_called_once()


def test_hybrid_invokes_only_air_pollution_advisory_facet():
    incident, _ = _incident(hybrid=True)
    handler, _ = _working_handler()

    results = dispatch_incidents(
        [incident],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )

    assert [(item.hazard, item.route, item.status) for item in results] == [
        ("fire", "emergency", "skipped"),
        ("air_pollution", "non_emergency", "partial"),
    ]
    detections = results[1].analysis_result.current_state.result.detections
    assert len(detections) == 1
    assert detections[0].hazard_type == "air_pollution"


def test_unsupported_hazard_is_reported_without_crashing():
    incident, _ = _incident(hybrid=True)
    incident["hazards"] = [FIRE]
    incident["queues"] = ["emergency"]

    result = dispatch_incidents([incident], registry={}, at=REQUESTED_AT)[0]

    assert result.status == "skipped"
    assert result.failure_reason == "unsupported_hazard_route"


def test_analysis_and_planner_failures_are_isolated():
    incident_a, _ = _incident(identifier="INC-AP-A")
    incident_b, _ = _incident(identifier="INC-AP-B")
    analyzer = Mock()
    analyzer.analyze.side_effect = [RuntimeError("analysis failed"), Mock(status="partial")]
    planner = Mock()
    planner.plan_response.side_effect = RuntimeError("planner failed")
    handler = AirPollutionIncidentHandler(
        analyzer=analyzer,
        planner=planner,
        clock=lambda: GENERATED_AT,
    )

    results = dispatch_incidents(
        [incident_a, incident_b],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )

    assert [item.failure_stage for item in results] == ["analysis", "planning"]
    assert all(item.status == "failed" for item in results)
    assert results[1].analysis_result is not None


def test_dispatch_touched_loads_only_supplied_incident_ids():
    incident, _ = _incident()
    handler, _ = _working_handler()
    reads = []

    results = dispatch_touched(
        [incident["id"], incident["id"]],
        registry={("air_pollution", "non_emergency"): handler},
        incident_reader=lambda identifier: reads.append(identifier) or incident,
        at=REQUESTED_AT,
    )

    assert reads == [incident["id"]]
    assert len(results) == 1


def test_hybrid_merge_cause_is_in_coordinator_touched_ids():
    result = CoordinationResult(
        created=["INC-POLLUTION-EFFECT"],
        linked=[{
            "cause_incident": "INC-FIRE-CAUSE",
            "effect_hazard": "air_pollution",
        }],
    )

    assert result.touched_ids == ["INC-POLLUTION-EFFECT", "INC-FIRE-CAUSE"]
