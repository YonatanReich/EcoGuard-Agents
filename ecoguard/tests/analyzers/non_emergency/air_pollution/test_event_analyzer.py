from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from ecoguard.detectors.air_pollution.schemas import AirPollutionAnomaly, AirPollutionBaselineEvidence
from ecoguard.detectors.air_pollution.correlation import correlation_candidate
from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import AirPollutionAnalysisInput
from ecoguard.analyzers.non_emergency.air_pollution.event_analyzer import AirPollutionNonEmergencyAnalyzer
from ecoguard.detectors.air_pollution.spatial_schemas import (
    PollutionSpatialContext,
    SpatiallyEnrichedAirPollutionAnomaly,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_schemas import (
    AnalysisOrigin,
    TransportEvidenceReference,
    WindEvidence,
)
from ecoguard.analyzers.non_emergency.air_pollution.analysis_adapter import (
    adapt_non_emergency_air_pollution_analysis_input,
)
from ecoguard.detectors.air_pollution.baseline_schemas import (
    BaselineBucketStatistics,
    BaselineIdentity,
    BaselineVersionProvenance,
    LiveObservationContext,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_prediction_service import (
    AirPollutionTransportConfiguration,
    AirPollutionTransportPredictionService,
)
from ecoguard.shared.air_quality_schemas import (
    MinistryAirQualityIndexEvidence,
    MinistryAirQualityIndexLookupResult,
)

OBSERVED_AT = datetime(2026, 9, 13, 17, 15, tzinfo=timezone.utc)
REQUESTED_AT = OBSERVED_AT + timedelta(minutes=2)
GENERATED_AT = REQUESTED_AT + timedelta(seconds=1)
POINT = {"latitude": 32.1, "longitude": 34.8}


def _candidate(*, live_value: float = 21.0, baseline_p95: float = 20.0):
    live = LiveObservationContext(
        provider="israel_ministry_environment_air_monitoring",
        station_id="42",
        channel_id="7001",
        pollutant="NO2",
        value=live_value,
        observed_at=OBSERVED_AT,
        provider_timestamp="2026-09-13 19:15:00",
        measurement_unit="ppb",
        unit_source="reading",
        reading_unit="ppb",
        location=POINT,
    )
    identity = BaselineIdentity(
        provider=live.provider,
        station_id=live.station_id,
        channel_id=live.channel_id,
        pollutant=live.pollutant,
        canonical_unit=live.measurement_unit,
        baseline_family="five_minute_observation",
    )
    stats = BaselineBucketStatistics(
        status="ok",
        sample_count=120,
        distinct_days=80,
        distinct_years=5,
        years_present=[2021, 2022, 2023, 2024, 2025],
        mean=8.0,
        median=7.0,
        std=3.0,
        mad=1.5,
        p05=2.0,
        p25=4.0,
        p75=12.0,
        p95=baseline_p95,
    )
    version = BaselineVersionProvenance(
        baseline_version_id=77,
        content_sha256="a" * 64,
        coverage_status="FULL_BASELINE",
        lifecycle_status="active",
        schema_version="air-pollution-baseline-profile-v2",
        method_version="national-v2-five-minute",
        source_name="Israeli Ministry / Envista",
        source_version="2021-2025",
        training_start=date(2021, 1, 1),
        training_end=date(2025, 12, 31),
        imported_at=OBSERVED_AT,
        aggregation_policy_version="provider-five-minute-month-hour-v1",
        quality_policy_version="ecoguard-provider-valid-signed-v1",
        source_metadata={},
        aggregation_metadata={},
        quality_metadata={},
        coverage_metadata={},
    )
    evidence = AirPollutionBaselineEvidence(
        identity=identity,
        month=9,
        hour=19,
        statistics=stats,
        version=version,
    )
    anomaly = AirPollutionAnomaly(
        detection_id="air-pollution:test",
        observed_at=OBSERVED_AT,
        detected_at=OBSERVED_AT + timedelta(seconds=10),
        location=POINT,
        provider=live.provider,
        station_id=live.station_id,
        station_name="Central Station",
        channel_id=live.channel_id,
        pollutant=live.pollutant,
        value=live.value,
        unit=live.measurement_unit,
        live_observation=live,
        detector_reason="live_value_above_baseline_p95",
        detector_rule_version="air-pollution-five-minute-p95-v1",
        baseline_evidence=evidence,
    )
    spatial = PollutionSpatialContext(
        location=POINT,
        lookup_radius_km=2.0,
        status="success",
        source="OpenStreetMap / Overpass API",
        collected_at=OBSERVED_AT,
        provider_collection_status="success",
        nearby_settlements=[
            {
                "name": "East Town",
                "type": "town",
                "osm_id": 123,
                "osm_type": "node",
                "latitude": 32.1,
                "longitude": 34.81,
            }
        ],
    )
    return correlation_candidate(
        SpatiallyEnrichedAirPollutionAnomaly(anomaly=anomaly, spatial_context=spatial)
    )


def _incident_evidence():
    return [
        TransportEvidenceReference(
            evidence_id="coordinator-evidence-1",
            source_name="shared-coordinator",
            source_type="correlated_detection_group",
            metadata={"detection_ids": ["air-pollution:test"]},
        )
    ]


def _analysis_input(candidate=None, **changes):
    candidate = candidate or _candidate()
    values = {
        "incident_id": "incident-external-1",
        "analysis_id": "analysis-external-1",
        "coordinator_routing_id": "routing-external-1",
        "route": "non_emergency",
        "routed_by": "future-shared-coordinator",
        "routed_at": REQUESTED_AT - timedelta(seconds=1),
        "requested_at": REQUESTED_AT,
        "analysis_origin": AnalysisOrigin(
            analysis_origin_kind="monitoring_location",
            analysis_origin_coordinates=POINT,
            evidence_reference_ids=["coordinator-evidence-1"],
        ),
        "correlated_detections": [candidate],
        "evidence": _incident_evidence(),
    }
    values.update(changes)
    return adapt_non_emergency_air_pollution_analysis_input(**values)


def _wind() -> WindEvidence:
    return WindEvidence(
        evidence_id="ims-wind:10:2026-09-13T17:15:00Z",
        provider="Israel Meteorological Service",
        source_type="station_observation",
        provider_location_kind="station",
        provider_location_id="10",
        provider_location_name="Test Wind Station",
        requested_coordinates=POINT,
        actual_provider_coordinates={"latitude": 32.11, "longitude": 34.79},
        raw_provider_timestamp="2026-09-13T19:15:00+02:00",
        wind_observed_at=OBSERVED_AT,
        retrieved_at=REQUESTED_AT,
        wind_from_direction_deg=270.0,
        wind_speed_mps=5.0,
        provider_validity="valid",
        provider_status="valid",
        provider_channel_validity={"WD": "valid", "WS": "valid"},
        original_units={"wind_direction": "degrees", "wind_speed": "m/s"},
        time_offset_from_anomaly_seconds=0.0,
        reference="IMS station observation",
    )


def _transport_service(wind_provider=None):
    wind_provider = wind_provider or Mock()
    wind_provider.select_wind_evidence.return_value = SimpleNamespace(
        wind_evidence=_wind()
    )
    service = AirPollutionTransportPredictionService(
        wind_evidence_service=wind_provider,
        configuration=AirPollutionTransportConfiguration(
            corridor_half_angle_deg=45.0,
            max_screening_distance_m=10_000.0,
            arc_segment_count=8,
            wind_max_age_minutes=30.0,
            minimum_wind_speed_mps=0.5,
        ),
    )
    return service, wind_provider


def _index_lookup(*, status="available", reason=None, **changes):
    if status == "unavailable":
        return MinistryAirQualityIndexLookupResult(
            status="unavailable", reason=reason or "index_unavailable"
        )
    values = {
        "station_id": "42",
        "station_index": 67.0,
        "station_category": "טובה",
        "category_color": "#00A651",
        "driving_pollutant": "NO2",
        "pollutant": "NO2",
        "pollutant_sub_index": 71.0,
        "monitor_id": "7001",
        "resolved_channel_id": "7001",
        "averaged_concentration": 19.0,
        "canonical_unit": "ppb",
        "provider_unit": "ppb",
        "unit_source": "station_metadata",
        "averaging_period_minutes": 60,
        "provider_timestamp": OBSERVED_AT + timedelta(minutes=15),
        "raw_provider_timestamp": "2026-09-13T19:30:00+02:00",
        "evidence_id": "ministry-aqi:42:7001:NO2:2026-09-13T17:30:00+00:00",
        "retrieved_at": REQUESTED_AT,
        "limitations": [
            "Source-native Ministry category; no EcoGuard LOW/MEDIUM/HIGH mapping.",
            "Preliminary provider data may change after validation.",
            "The index concentration uses its provider averaging window and is not the triggering five-minute measurement.",
        ],
    }
    values.update(changes)
    return MinistryAirQualityIndexLookupResult(
        status="available", evidence=MinistryAirQualityIndexEvidence(**values)
    )


def test_external_coordinator_values_adapt_correlated_evidence():
    result = _analysis_input()

    assert isinstance(result, AirPollutionAnalysisInput)
    assert result.routing.route == "non_emergency"
    assert result.incident_id == "incident-external-1"
    assert result.analysis_id == "analysis-external-1"
    assert result.coordinator_routing_id == "routing-external-1"
    assert result.current_state.result.detections[0].anomaly.detection_id == "air-pollution:test"


@pytest.mark.parametrize("field", ["incident_id", "analysis_id", "coordinator_routing_id"])
def test_adapter_does_not_invent_coordinator_identifiers(field):
    with pytest.raises(ValidationError):
        _analysis_input(**{field: ""})


def test_analyzer_rejects_non_air_pollution_or_emergency_input():
    with pytest.raises(ValueError, match="non_emergency"):
        _analysis_input(route="emergency")
    payload = _analysis_input().model_dump(round_trip=True)
    payload["hazard_type"] = "fire"
    with pytest.raises(ValidationError):
        AirPollutionAnalysisInput.model_validate(payload)


def test_analyzer_composes_existing_wind_corridor_time_and_spatial_output():
    service, wind_provider = _transport_service()
    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=service, clock=lambda: GENERATED_AT
    ).analyze(_analysis_input())

    wind_provider.select_wind_evidence.assert_called_once()
    assert report.status == "partial"
    assert report.transport_analysis.status in {"success", "partial"}
    execution = report.transport_analysis.result
    assert execution.wind_evidence.evidence_id.startswith("ims-wind:")
    assert execution.analysis_origin.evidence_reference_ids == ["coordinator-evidence-1"]
    assert execution.spatial_output.centerline is not None
    assert execution.spatial_output.corridor_polygon is not None
    assert execution.spatial_output.downwind_to_direction_deg == 90.0
    assert execution.spatial_output.settlements[0].name == "East Town"
    assert execution.spatial_output.settlements[0].kinematic_advection_time_seconds is not None
    assert execution.spatial_output.exposure_not_confirmed is True
    assert any("not confirmed" in item.lower() for item in execution.spatial_output.limitations)


def test_analyzer_does_not_repeat_detector_p95_decision():
    # Deliberately inconsistent synthetic detector evidence: Analyzer must
    # preserve the upstream event and perform transport composition only.
    candidate = _candidate(live_value=1.0, baseline_p95=999.0)
    service, _ = _transport_service()

    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=service, clock=lambda: GENERATED_AT
    ).analyze(_analysis_input(candidate))

    retained = report.current_state.result.detections[0].anomaly
    assert retained.value == 1.0
    assert retained.baseline_evidence.statistics.p95 == 999.0
    assert report.transport_analysis.result is not None


def test_missing_wind_is_explicit_and_safe():
    wind_provider = Mock()
    wind_provider.select_wind_evidence.side_effect = RuntimeError("provider unavailable")
    service, _ = _transport_service(wind_provider)

    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=service, clock=lambda: GENERATED_AT
    ).analyze(_analysis_input())

    assert report.transport_analysis.status == "unavailable"
    assert report.transport_analysis.result is None
    assert report.transport_analysis.unavailable_reason == (
        "wind_evidence_or_transport_screening_unavailable"
    )
    assert "provider unavailable" not in report.model_dump_json()


def test_unimplemented_population_trend_and_severity_are_not_fabricated():
    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=None, clock=lambda: GENERATED_AT
    ).analyze(_analysis_input())

    assert report.future_prediction.status == "unavailable"
    assert report.population_impact.status == "unavailable"
    assert report.severity_assessment.status == "unavailable"
    assert report.transport_analysis.status == "unavailable"
    assert report.exposure_not_confirmed is True


def test_analyzer_preserves_native_ministry_index_separately_from_p95_evidence():
    index_client = Mock()
    index_client.get_station_index_evidence.return_value = _index_lookup()
    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=None,
        ministry_index_client=index_client,
        clock=lambda: GENERATED_AT,
    ).analyze(_analysis_input())

    index_client.get_station_index_evidence.assert_called_once_with(
        station_id="42",
        channel_id="7001",
        pollutant="NO2",
        observed_at=OBSERVED_AT,
    )
    assert report.severity_assessment.status == "partial"
    assessment = report.severity_assessment.result
    assert assessment.ecoguard_severity_level is None
    assert assessment.ministry_index.station_category == "טובה"
    assert assessment.ministry_index.averaging_period_minutes == 60
    assert assessment.five_minute_anomaly_evidence_is_separate is True
    anomaly = report.current_state.result.detections[0].anomaly
    assert anomaly.baseline_evidence.statistics.p95 == 20.0
    assert assessment.ministry_index.averaged_concentration == 19.0
    assert report.severity_assessment.evidence[0].evidence_id.startswith("ministry-aqi:")


def test_analyzer_native_index_unavailable_and_identity_mismatch_fail_closed():
    index_client = Mock()
    index_client.get_station_index_evidence.return_value = _index_lookup(
        status="unavailable", reason="no_valid_index"
    )
    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=None,
        ministry_index_client=index_client,
        clock=lambda: GENERATED_AT,
    ).analyze(_analysis_input())
    assert report.severity_assessment.status == "unavailable"
    assert report.severity_assessment.unavailable_reason == "no_valid_index"

    index_client.get_station_index_evidence.return_value = _index_lookup(
        station_id="999"
    )
    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=None,
        ministry_index_client=index_client,
        clock=lambda: GENERATED_AT,
    ).analyze(_analysis_input())
    assert report.severity_assessment.status == "unavailable"
    assert report.severity_assessment.unavailable_reason == (
        "ministry_air_quality_index_identity_mismatch"
    )


def test_analyzer_stack_has_no_database_runtime_store_scheduler_or_planner_dependency():
    import ecoguard.analyzers.non_emergency.air_pollution.event_analyzer as analyzer_module
    import ecoguard.analyzers.non_emergency.air_pollution.analysis_adapter as adapter_module

    names = set(analyzer_module.__dict__) | set(adapter_module.__dict__)
    assert not {
        "Session",
        "AirPollutionRuntimeService",
        "InMemoryAirPollutionEventStore",
        "Scheduler",
        "ResponsePlanner",
    } & names
