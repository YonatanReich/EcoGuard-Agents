from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from ecoguard.detectors.air_pollution.schemas import (
    AirPollutionAnomaly,
    AirPollutionBaselineEvidence,
    AirPollutionDetectionResult,
)
from ecoguard.detectors.air_pollution.correlation import (
    PollutionCorrelationCandidate,
    compare_pollution_candidates,
    correlation_candidate,
)
from ecoguard.detectors.air_pollution.spatial_enrichment import (
    LAYERS,
    AirPollutionSpatialEnricher,
)
from ecoguard.detectors.air_pollution.spatial_schemas import SpatiallyEnrichedAirPollutionAnomaly
from ecoguard.database.repositories.localities import (
    LocalityCandidate,
    LocalityLookupResult,
    LocalityLookupStatus,
)
from ecoguard.detectors.air_pollution.baseline_schemas import (
    BaselineBucketStatistics,
    BaselineIdentity,
    BaselineVersionProvenance,
    LiveObservationContext,
)

OBSERVED_AT = datetime(2026, 9, 13, 17, 15, tzinfo=timezone.utc)
POINT = {"latitude": 32.1, "longitude": 34.8}


def _anomaly(
    detection_id: str = "air-pollution:test-a",
    *,
    pollutant: str = "NO2",
    minutes: float = 0,
    latitude: float = 32.1,
    longitude: float = 34.8,
    station_id: str = "42",
    channel_id: str = "7001",
) -> AirPollutionAnomaly:
    observed_at = OBSERVED_AT + timedelta(minutes=minutes)
    location = {"latitude": latitude, "longitude": longitude}
    live = LiveObservationContext(
        provider="israel_ministry_environment_air_monitoring",
        station_id=station_id,
        channel_id=channel_id,
        pollutant=pollutant,
        value=21.0,
        observed_at=observed_at,
        provider_timestamp="2026-09-13 19:15:00",
        measurement_unit="ppb",
        unit_source="reading",
        reading_unit="ppb",
        location=location,
    )
    identity = BaselineIdentity(
        provider=live.provider,
        station_id=station_id,
        channel_id=channel_id,
        pollutant=pollutant,
        canonical_unit="ppb",
        baseline_family="five_minute_observation",
    )
    statistics = BaselineBucketStatistics(
        status="ok",
        sample_count=150,
        distinct_days=100,
        distinct_years=5,
        years_present=[2021, 2022, 2023, 2024, 2025],
        mean=8.0,
        median=7.0,
        std=3.0,
        mad=1.5,
        p05=2.0,
        p25=4.0,
        p75=12.0,
        p95=20.0,
    )
    version = BaselineVersionProvenance(
        baseline_version_id=77,
        content_sha256="a" * 64,
        coverage_status="FULL_BASELINE",
        lifecycle_status="draft",
        schema_version="air-pollution-baseline-profile-v2",
        method_version="national-v2-five-minute",
        source_name="Israeli Ministry / Envista",
        source_version="2021-2025",
        training_start=date(2021, 1, 1),
        training_end=date(2025, 12, 31),
        imported_at=OBSERVED_AT,
        aggregation_policy_version="provider-five-minute-month-hour-v1",
        quality_policy_version="ecoguard-provider-valid-signed-v1",
        source_metadata={"official": True},
        aggregation_metadata={},
        quality_metadata={"signed_values": "preserved"},
        coverage_metadata={},
    )
    evidence = AirPollutionBaselineEvidence(
        identity=identity,
        month=9,
        hour=19,
        statistics=statistics,
        version=version,
    )
    return AirPollutionAnomaly(
        detection_id=detection_id,
        observed_at=observed_at,
        detected_at=observed_at + timedelta(seconds=10),
        location=location,
        provider=live.provider,
        station_id=station_id,
        station_name="Central Station",
        channel_id=channel_id,
        pollutant=pollutant,
        value=live.value,
        unit="ppb",
        live_observation=live,
        detector_reason="live_value_above_baseline_p95",
        detector_rule_version="air-pollution-five-minute-p95-v1",
        baseline_evidence=evidence,
    )


def _detection(status: str) -> AirPollutionDetectionResult:
    if status == "SUSPECTED_ANOMALY":
        anomaly = _anomaly()
        return AirPollutionDetectionResult(
            status=status,
            reason="live_value_above_baseline_p95",
            detector_rule_version=anomaly.detector_rule_version,
            live_observation=anomaly.live_observation,
            baseline_evidence=anomaly.baseline_evidence,
            anomaly=anomaly,
        )
    return AirPollutionDetectionResult(
        status=status,
        reason="not_downstream_eligible",
        detector_rule_version="air-pollution-five-minute-p95-v1",
    )


def _context(*, feature_name: str = "Test town") -> dict:
    layers = {layer: [] for layer in LAYERS}
    layers["nearby_settlements"] = [
        {
            "name": feature_name,
            "type": "town",
            "osm_id": 42,
            "osm_type": "node",
            "latitude": 32.1,
            "longitude": 34.8,
            "population": "1200",
        }
    ]
    return {
        "metadata": {
            "data_source": "OpenStreetMap / Overpass API",
            "collection_status": "success",
            "timestamp": "2026-09-13T17:16:00Z",
        },
        "location": {**POINT, "radius_km": 2.0},
        "geospatial_context": layers,
        "missing_layers": [],
    }


def _locality_lookup(*, name: str = "Test town", longitude: float = 34.8):
    def lookup(**_):
        return LocalityLookupResult(
            status=LocalityLookupStatus.SUCCESS_WITH_RESULTS,
            candidates=[LocalityCandidate(
                locality_code="5000",
                name_he=name,
                locality_type="town",
                latitude=32.1,
                longitude=longitude,
                distance_m=0.0,
                source="official-localities",
            )],
        )
    return lookup


def test_suspected_anomaly_enters_spatial_enrichment():
    provider = Mock()
    provider.fetch_nearby_context.return_value = _context()

    result = AirPollutionSpatialEnricher(
        provider, locality_lookup=_locality_lookup()
    ).enrich_detection_result(
        _detection("SUSPECTED_ANOMALY")
    )

    provider.fetch_nearby_context.assert_called_once_with(32.1, 34.8, radius_km=2.0)
    assert isinstance(result, SpatiallyEnrichedAirPollutionAnomaly)


def test_default_air_pollution_enrichment_uses_db_localities_without_overpass():
    lookup = Mock(return_value=LocalityLookupResult(
        status=LocalityLookupStatus.SUCCESS_EMPTY,
    ))

    result = AirPollutionSpatialEnricher(locality_lookup=lookup).enrich(
        _anomaly(), radius_km=10.0
    )

    lookup.assert_called_once_with(latitude=32.1, longitude=34.8, radius_m=10_000.0)
    assert result.spatial_context.settlement_context.outcome == "SUCCESS_EMPTY"
    assert result.spatial_context.status == "success"
    assert result.spatial_context.nearby_settlements == []


def test_unloaded_locality_layer_remains_explicitly_unavailable():
    lookup = Mock(return_value=LocalityLookupResult(
        status=LocalityLookupStatus.REFERENCE_DATA_NOT_LOADED,
        reason="reference_data_not_loaded",
    ))

    result = AirPollutionSpatialEnricher(locality_lookup=lookup).enrich(_anomaly())

    settlement_context = result.spatial_context.settlement_context
    assert settlement_context.status == "unavailable"
    assert settlement_context.reason == "reference_data_not_loaded"
    assert result.spatial_context.status == "unavailable"
    assert "nearby_settlements" in result.spatial_context.missing_layers


def test_overpass_settlements_are_ignored_but_other_layers_are_preserved():
    supplied = _context(feature_name="Overpass town")
    supplied["geospatial_context"]["nearby_roads"] = [{"name": "Road 1"}]

    result = AirPollutionSpatialEnricher(
        locality_lookup=_locality_lookup(name="Database town")
    ).enrich(_anomaly(), geospatial_context=supplied)

    assert [item.name for item in result.spatial_context.nearby_settlements] == [
        "Database town"
    ]
    assert [item.name for item in result.spatial_context.nearby_roads] == ["Road 1"]


@pytest.mark.parametrize("status", ["NORMAL", "NOT_EVALUATED"])
def test_non_anomalies_do_not_enter_spatial_enrichment(status):
    provider = Mock()

    assert AirPollutionSpatialEnricher(provider).enrich_detection_result(
        _detection(status)
    ) is None
    provider.fetch_nearby_context.assert_not_called()


def test_identity_location_and_supplied_geographic_context_are_preserved():
    anomaly = _anomaly()
    provider = Mock()

    result = AirPollutionSpatialEnricher(
        provider, locality_lookup=_locality_lookup()
    ).enrich(
        anomaly, geospatial_context=_context()
    )

    provider.fetch_nearby_context.assert_not_called()
    assert result.anomaly == anomaly
    assert result.anomaly.station_id == "42"
    assert result.anomaly.station_name == "Central Station"
    assert result.spatial_context.location == anomaly.location
    settlement = result.spatial_context.nearby_settlements[0]
    assert (settlement.name, settlement.ref, settlement.osm_id) == (
        "Test town", "5000", None
    )


def test_enriched_anomaly_enters_correlation_with_all_detector_evidence():
    enriched = AirPollutionSpatialEnricher(
        Mock(), locality_lookup=_locality_lookup()
    ).enrich(
        _anomaly(), geospatial_context=_context()
    )

    candidate = correlation_candidate(enriched)

    assert candidate.anomaly == enriched.anomaly
    assert candidate.spatial_context == enriched.spatial_context
    assert candidate.station_channels == [
        ("israel_ministry_environment_air_monitoring", "42", "7001")
    ]
    assert ("detector_rule", "air-pollution-five-minute-p95-v1") in candidate.evidence_references
    assert ("baseline_version", "77") in candidate.evidence_references
    assert ("baseline_content_sha256", "a" * 64) in candidate.evidence_references
    assert candidate.anomaly.baseline_evidence.statistics.p95 == 20.0


def test_correlation_uses_time_location_pollutant_and_geographic_evidence():
    left = correlation_candidate(
        AirPollutionSpatialEnricher(
            Mock(), locality_lookup=_locality_lookup()
        ).enrich(
            _anomaly(), geospatial_context=_context()
        )
    )
    right_context = _context()
    right_context["location"]["longitude"] = 34.81
    right_context["geospatial_context"]["nearby_settlements"][0]["longitude"] = 34.8
    right = correlation_candidate(
        AirPollutionSpatialEnricher(
            Mock(), locality_lookup=_locality_lookup()
        ).enrich(
            _anomaly("air-pollution:test-b", minutes=2, longitude=34.81),
            geospatial_context=right_context,
        )
    )

    result = compare_pollution_candidates(left, right)

    assert result.candidate_match
    assert result.temporal_distance_seconds == 120
    assert 0.8 < result.spatial_distance_km < 1.1
    assert {
        "within_time_window",
        "within_distance_window",
        "same_pollutant",
        "overlapping_geographic_context",
    } <= set(result.matching_signals)
    assert ("baseline_version", "77") in result.evidence_references


def test_incompatible_pollutant_is_supporting_conflict_not_incident_decision():
    result = compare_pollution_candidates(
        correlation_candidate(_anomaly()),
        correlation_candidate(_anomaly("air-pollution:test-b", pollutant="SO2")),
    )

    assert not result.candidate_match
    assert "pollutant_incompatible" in result.conflicting_signals
    payload = result.model_dump()
    assert not {
        "incident",
        "emergency",
        "severity",
        "confidence",
        "affected_area",
        "transport",
        "corridor",
        "response_plan",
    } & payload.keys()


def test_correlation_rejects_downstream_operational_fields():
    candidate = correlation_candidate(_anomaly())
    for field in ("incident", "emergency", "transport", "response_plan"):
        with pytest.raises(ValidationError):
            PollutionCorrelationCandidate.model_validate(
                {**candidate.model_dump(round_trip=True), field: True}
            )


def test_modules_have_no_old_runtime_or_event_store_dependency():
    import ecoguard.detectors.air_pollution.correlation as correlation_module
    import ecoguard.detectors.air_pollution.spatial_enrichment as enrichment_module

    names = set(correlation_module.__dict__) | set(enrichment_module.__dict__)
    assert not {
        "InMemoryAirPollutionEventStore",
        "AirPollutionRuntimeService",
        "TransportAnalysisService",
    } & names
