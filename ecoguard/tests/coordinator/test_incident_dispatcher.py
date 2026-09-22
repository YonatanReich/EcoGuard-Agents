"""Shared incident dispatch and Air Pollution production-handler tests."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import (
    AirPollutionTrendPrediction,
    AnalysisComponent,
)
from ecoguard.analyzers.non_emergency.air_pollution.additional_verification import (
    AirPollutionAdditionalVerificationService,
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
from ecoguard.analyzers.non_emergency.air_pollution.wind_evidence_service import (
    PersistedFirstWindEvidenceService,
)
from ecoguard.coordinator.agent import CoordinationResult
from ecoguard.coordinator.dispatcher import dispatch_incidents, dispatch_touched
from ecoguard.coordinator.incidents import signal_as_json
from ecoguard.detectors.air_pollution.cell_signal_adapter import (
    air_pollution_candidate_to_cell_signal,
)
from ecoguard.detectors.air_pollution.correlation import PollutionCorrelationCandidate
from ecoguard.detectors.air_pollution.spatial_schemas import (
    SpatiallyEnrichedAirPollutionAnomaly,
)
from ecoguard.response_planner.air_pollution.schemas import AirPollutionPlanningResult
from ecoguard.shared.signals import FIRE, HIGH, CellSignal
from ecoguard.tests.analyzers.non_emergency.air_pollution.test_event_analyzer import (
    GENERATED_AT,
    OBSERVED_AT,
    _candidate,
    _index_lookup,
    _transport_service,
    _wind,
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


def _path_a_incident(*, identifier="INC-AP-PATH-A"):
    incident, first = _incident(identifier=identifier)
    payload = first.model_dump(round_trip=True)
    anomaly = payload["anomaly"]
    anomaly["detection_id"] = "air-pollution:path-a-second-station"
    anomaly["station_id"] = "43"
    anomaly["station_name"] = "Second station"
    anomaly["live_observation"]["station_id"] = "43"
    anomaly["baseline_evidence"]["identity"]["station_id"] = "43"
    second = PollutionCorrelationCandidate.model_validate(payload)
    incident["signals"].append(
        signal_as_json(air_pollution_candidate_to_cell_signal(second))
    )
    incident["signal_count"] = 2
    return incident


def _working_handler(
    *,
    trend_component=None,
    pollutant_sub_index=71.0,
    verification_service=None,
    wind_evidence_provider=None,
    spatial_enricher=None,
    population_query=None,
):
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
    index.get_station_index_evidence.return_value = _index_lookup(
        pollutant_sub_index=pollutant_sub_index
    )
    population_query = population_query or Mock(return_value={
        "grid_available": True,
        "intersected_cell_count": 2,
        "weighted_population": 50.0,
    })
    population = AirPollutionPopulationAnalysisService(population_query)
    transport, _ = _transport_service(wind_evidence_provider)
    analyzer = AirPollutionNonEmergencyAnalyzer(
        transport_service=transport,
        ministry_index_client=index,
        population_service=population,
        trend_inference_service=trend,
        spatial_enricher=spatial_enricher,
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
        verification_service=verification_service,
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


def test_qualified_moderate_event_gets_context_only_without_firms_check():
    incident = _path_a_incident()
    firms_reads = []
    verification = AirPollutionAdditionalVerificationService(
        firms_run_reader=lambda: firms_reads.append(True)
    )
    handler, _ = _working_handler(
        pollutant_sub_index=25.0,
        verification_service=verification,
    )

    result = dispatch_incidents(
        [incident],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )[0]

    analysis = result.analysis_result
    assert result.route == "non_emergency"
    assert analysis.event_qualification.path == "PATH_A"
    assert analysis.official_pollutant_classification.classification == "MODERATE"
    assert analysis.publication_policy.publish_to_operational_dashboard is True
    assert analysis.publication_policy.emphasis == "standard"
    assert analysis.additional_verification.status == "CONTEXT_ONLY"
    assert firms_reads == []


def test_qualified_low_event_triggers_verification_and_preserves_advisory_route():
    incident = _path_a_incident()
    incident["links"] = [{
        "cause_hazard": "fire",
        "effect_hazard": "air_pollution",
        "cause_incident": "INC-FIRE-SUPPORT",
        "distance_km": 3.0,
        "bearing_deg": 120.0,
        "lag_hours": 1.0,
    }]
    handler, _ = _working_handler(pollutant_sub_index=-25.0)

    result = dispatch_incidents(
        [incident],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )[0]

    analysis = result.analysis_result
    assert result.route == "non_emergency"
    assert analysis.official_pollutant_classification.classification == "LOW"
    assert analysis.publication_policy.emphasis == "strong"
    assert analysis.additional_verification.status == "CORROBORATED"
    statement = analysis.additional_verification.possible_source_correlations[0].statement
    assert "does not confirm causation" in statement


def test_internal_incidents_never_pay_heavy_analysis_cost():
    wind = Mock()
    towns = Mock()
    population_query = Mock()
    handler, _ = _working_handler(
        pollutant_sub_index=71.0,
        wind_evidence_provider=wind,
        spatial_enricher=towns,
        population_query=population_query,
    )
    transport = Mock(wraps=handler._analyzer._transport_component)
    population = Mock(wraps=handler._analyzer._population_component)
    corridor = Mock(wraps=handler._analyzer._transport_service.predict)
    handler._analyzer._transport_component = transport
    handler._analyzer._population_component = population
    handler._analyzer._transport_service.predict = corridor
    incidents = [_incident(identifier=f"INC-INTERNAL-{index}")[0] for index in range(4)]

    results = dispatch_incidents(
        incidents,
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )

    assert len(results) == 4
    assert all(
        result.analysis_result.publication_policy.publish_to_operational_dashboard
        is False
        for result in results
    )
    assert all(
        result.analysis_result.transport_analysis.unavailable_reason
        == "not_run_for_non_publishable_event"
        for result in results
    )
    transport.assert_not_called()
    population.assert_not_called()
    wind.select_wind_evidence.assert_not_called()
    towns.enrich.assert_not_called()
    corridor.assert_not_called()
    population_query.assert_not_called()


def test_qualified_good_and_unknown_events_do_not_run_heavy_analysis():
    for pollutant_sub_index, expected in ((71.0, "GOOD"), (500.0, "UNKNOWN")):
        handler, _ = _working_handler(pollutant_sub_index=pollutant_sub_index)
        transport = Mock(wraps=handler._analyzer._transport_component)
        population = Mock(wraps=handler._analyzer._population_component)
        handler._analyzer._transport_component = transport
        handler._analyzer._population_component = population

        result = dispatch_incidents(
            [_path_a_incident(identifier=f"INC-{expected}")],
            registry={("air_pollution", "non_emergency"): handler},
            at=REQUESTED_AT,
        )[0]

        assert result.analysis_result.event_qualification.path == "PATH_A"
        assert (
            result.analysis_result.official_pollutant_classification.classification
            == expected
        )
        assert result.analysis_result.publication_policy.publish_to_operational_dashboard is False
        transport.assert_not_called()
        population.assert_not_called()


def test_publishable_event_runs_transport_and_population_once():
    handler, _ = _working_handler(pollutant_sub_index=25.0)
    transport = Mock(wraps=handler._analyzer._transport_component)
    population = Mock(wraps=handler._analyzer._population_component)
    handler._analyzer._transport_component = transport
    handler._analyzer._population_component = population

    result = dispatch_incidents(
        [_path_a_incident()],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )[0]

    assert result.analysis_result.publication_policy.publish_to_operational_dashboard is True
    transport.assert_called_once()
    population.assert_called_once()


def test_publishable_event_uses_fresh_db_wind_then_towns_corridor_and_population():
    candidate = _candidate()
    reader = Mock(return_value={
        "source": "weather",
        "cell_id": "weather-grid:1",
        "observed_at": OBSERVED_AT - timedelta(minutes=10),
        "latitude": candidate.anomaly.location.latitude,
        "longitude": candidate.anomaly.location.longitude,
        "distance_m": 0.0,
        "payload": {
            "wind_speed_10m": 18.0,
            "wind_direction_10m": 270.0,
            "wind_gusts_10m": 25.2,
        },
    })
    live = Mock()
    wind = PersistedFirstWindEvidenceService(
        live,
        reader=reader,
        writer=Mock(),
        clock=lambda: GENERATED_AT,
    )
    spatial = Mock()
    spatial.enrich.return_value = SpatiallyEnrichedAirPollutionAnomaly(
        anomaly=candidate.anomaly,
        spatial_context=candidate.spatial_context,
    )
    population_query = Mock(return_value={
        "grid_available": True,
        "intersected_cell_count": 2,
        "weighted_population": 50.0,
    })
    handler, _ = _working_handler(
        pollutant_sub_index=25.0,
        wind_evidence_provider=wind,
        spatial_enricher=spatial,
        population_query=population_query,
    )

    result = dispatch_incidents(
        [_path_a_incident()],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )[0]

    analysis = result.analysis_result
    assert analysis.transport_analysis.result.wind_evidence.provider == "Open-Meteo"
    assert analysis.transport_analysis.result.spatial_output.corridor_polygon is not None
    assert analysis.population_impact.result.total_relevant_population == 50
    live.select_wind_evidence.assert_not_called()
    spatial.enrich.assert_called_once()
    population_query.assert_called_once()


def test_publishable_event_falls_back_live_persists_and_runs_downstream():
    candidate = _candidate()
    live = Mock()
    live.select_wind_evidence.return_value = SimpleNamespace(wind_evidence=_wind())
    writer = Mock(return_value=1)
    wind = PersistedFirstWindEvidenceService(
        live,
        reader=Mock(return_value=None),
        writer=writer,
        clock=lambda: GENERATED_AT,
    )
    spatial = Mock()
    spatial.enrich.return_value = SpatiallyEnrichedAirPollutionAnomaly(
        anomaly=candidate.anomaly,
        spatial_context=candidate.spatial_context,
    )
    population_query = Mock(return_value={
        "grid_available": True,
        "intersected_cell_count": 2,
        "weighted_population": 50.0,
    })
    handler, _ = _working_handler(
        pollutant_sub_index=25.0,
        wind_evidence_provider=wind,
        spatial_enricher=spatial,
        population_query=population_query,
    )

    result = dispatch_incidents(
        [_path_a_incident()],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )[0]

    assert result.analysis_result.transport_analysis.result.wind_evidence.provider == "IMS"
    live.select_wind_evidence.assert_called_once()
    writer.assert_called_once()
    spatial.enrich.assert_called_once()
    population_query.assert_called_once()


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
    analyzer.assess_official_index.return_value = AnalysisComponent(
        status="unavailable",
        unavailable_reason="ministry_air_quality_index_lookup_unavailable",
    )
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


def test_fresh_plan_is_not_rebuilt_by_a_routine_re_dispatch():
    """The loop that re-planned one unchanged incident on every tick.

    An open incident is touched by every routine signal that lands on it, and
    the air pollution and earthquake handlers rebuild their plan on every
    touch. A successful plan from a minute ago stands instead.
    """
    from ecoguard.coordinator import dispatcher as module

    calls: list[str] = []

    class CountingHandler:
        name = "counting"

        def process(self, incident, context):
            calls.append(context.incident_id)
            return module.IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="success",
                requested_at=context.requested_at,
                completed_at=context.requested_at,
            )

    now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    incident = {
        "id": "INC-1",
        "status": "open",
        "primary_hazard": "air_pollution",
        "hazards": ["air_pollution"],
        "queues": ["non_emergency"],
    }
    registry = {("air_pollution", "non_emergency"): CountingHandler()}

    fresh = dispatch_incidents(
        [incident],
        registry=registry,
        at=now,
        projection_reader=lambda _: {"last_success_at": now - timedelta(minutes=1)},
    )
    assert calls == []
    assert fresh == []

    dispatch_incidents(
        [incident],
        registry=registry,
        at=now,
        projection_reader=lambda _: {
            "last_success_at": now - timedelta(minutes=module.PLAN_REFRESH_MINUTES + 1)
        },
    )
    assert calls == ["INC-1"]

    dispatch_incidents(
        [incident], registry=registry, at=now, projection_reader=lambda _: None
    )
    assert calls == ["INC-1", "INC-1"]


def test_settled_non_retryable_outcome_waits_the_window_too():
    """A partial-but-planned or policy-skipped result must not re-run every tick.

    Such projections never get a last_success_at, so before this they were
    re-dispatched on every sweep — deterministic work and a projection rewrite
    for nineteen sub-threshold readings, ten times an hour.
    """
    from ecoguard.coordinator import dispatcher as module

    now = datetime(2026, 9, 22, 3, 0, tzinfo=timezone.utc)
    recent = now - timedelta(minutes=5)
    stale = now - timedelta(minutes=module.PLAN_REFRESH_MINUTES + 1)

    settled = {"last_success_at": None, "last_attempt_at": recent, "retryable": False}
    assert module.plan_is_fresh("INC-1", now, lambda _: settled) is True

    retryable = {"last_success_at": None, "last_attempt_at": recent, "retryable": True}
    assert module.plan_is_fresh("INC-1", now, lambda _: retryable) is False

    old = {"last_success_at": None, "last_attempt_at": stale, "retryable": False}
    assert module.plan_is_fresh("INC-1", now, lambda _: old) is False
