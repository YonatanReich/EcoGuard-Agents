"""Persisted shared observation to active Air Pollution detector tests."""

from datetime import date, datetime, timezone

import pytest

from ecoguard.detectors.air_pollution.detector import AirPollutionAnomalyDetector
from ecoguard.detectors.air_pollution.baseline_schemas import (
    BaselineBucketStatistics,
    BaselineLookupResult,
    BaselineVersionProvenance,
)
from ecoguard.detectors.air_pollution.live_baseline import AirPollutionLiveBaselineContextService
from ecoguard.detectors.air_pollution.observation_processing import (
    AirPollutionObservationProcessor,
    RUN_SOURCE,
    air_quality_observation_from_row,
    detect_new,
)
from ecoguard.detectors.air_pollution.spatial_schemas import (
    NearbyGeographicFeature,
    PollutionSpatialContext,
    SpatiallyEnrichedAirPollutionAnomaly,
)
from ecoguard.shared.signals import AIR_POLLUTION
from ecoguard.shared.air_quality_schemas import AirQualityObservation, LIVE_QUALITY_POLICY

OBSERVED = datetime(2026, 9, 13, 17, 15, tzinfo=timezone.utc)
INGESTED = datetime(2026, 9, 13, 17, 16, tzinfo=timezone.utc)
DETECTED = datetime(2026, 9, 13, 17, 17, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _disable_real_transport_enrichment(monkeypatch):
    """Unit tests inject enrichment explicitly and never call Overpass."""

    monkeypatch.setenv("AIR_POLLUTION_TRANSPORT_SCREENING_ENABLED", "false")


def payload(value=10.0, **changes):
    data = {
        "provider": "israel_ministry_environment_air_monitoring",
        "provider_station_id": "42",
        "provider_channel_id": "7001",
        "location": {"latitude": 32.1, "longitude": 34.8},
        "pollutant": "NO2",
        "provider_pollutant_id": "8",
        "value": value,
        "unit": "ppb",
        "provider_unit": "ppb",
        "measurement_unit": "ppb",
        "reading_unit": "ppb",
        "metadata_unit": "ppb",
        "unit_source": "reading",
        "quality_policy": LIVE_QUALITY_POLICY,
        "observed_at": OBSERVED.isoformat(),
        "provider_timestamp": "2026-09-13T19:15:00+02:00",
        "valid": True,
        "provider_status_id": "1",
        "provider_status": "Normal",
        "quality_control": "preliminary_unvalidated",
        "source_id": "station:42",
        "collected_at": INGESTED.isoformat(),
        "collection_status": "success",
    }
    data.update(changes)
    return data


def row(identifier, value=10.0, **payload_changes):
    return {
        "id": identifier,
        "source": "air_pollution",
        "cell_id": f"ministry:42:7001:NO2:ppb:{identifier}",
        "observed_at": OBSERVED,
        "ingested_at": INGESTED,
        "latitude": 32.1,
        "longitude": 34.8,
        "payload": payload(value, **payload_changes),
    }


def version():
    return BaselineVersionProvenance(
        baseline_version_id=77,
        content_sha256="a" * 64,
        coverage_status="FULL_BASELINE",
        lifecycle_status="active",
        schema_version="air-pollution-five-minute-observation-baseline-v1",
        method_version="pooled-month-hour-five-minute-v1",
        source_name="Israeli Ministry / Envista",
        source_version="2021-2025",
        training_start=date(2021, 1, 1),
        training_end=date(2025, 12, 31),
        imported_at=INGESTED,
        aggregation_policy_version="historical-last-accepted-v1",
        quality_policy_version=LIVE_QUALITY_POLICY,
        source_metadata={},
        aggregation_metadata={},
        quality_metadata={},
        coverage_metadata={},
    )


def bucket(p95=20.0):
    return BaselineBucketStatistics(
        status="ok", sample_count=1000, distinct_days=100,
        distinct_years=5, years_present=[2021, 2022, 2023, 2024, 2025],
        mean=10.0, median=9.0, std=3.0, mad=1.5,
        p05=2.0, p25=5.0, p75=13.0, p95=p95,
    )


class ActiveOnlyLookup:
    def __init__(self):
        self.requests = []

    def lookup_batch(self, requests):
        self.requests.extend(requests)
        return [BaselineLookupResult(
            status="available",
            reason="exact_baseline_available",
            mode="operational",
            identity=request.identity,
            month=request.month,
            hour=request.hour,
            station_name="Station 42",
            version=version(),
            bucket=bucket(),
        ) for request in requests]

    def lookup_draft_batch_for_validation(self, requests):
        raise AssertionError("persisted processor must never use draft lookup")


class UnavailableActiveLookup(ActiveOnlyLookup):
    def lookup_batch(self, requests):
        self.requests.extend(requests)
        return [BaselineLookupResult(
            status="baseline_unavailable",
            reason="no_active_version",
            mode="operational",
            identity=request.identity,
            month=request.month,
            hour=request.hour,
        ) for request in requests]


def processor(lookup=None, **changes):
    lookup = lookup or ActiveOnlyLookup()
    return AirPollutionObservationProcessor(
        baseline_context_service=AirPollutionLiveBaselineContextService(lookup),
        detector=AirPollutionAnomalyDetector(clock=lambda: DETECTED),
        **changes,
    ), lookup


def test_adapter_maps_only_observation_fields_and_ignores_collector_envelope():
    item = row(1)
    item["payload"]["future_envelope_field"] = {"must": "be ignored"}

    observation = air_quality_observation_from_row(item)

    assert observation.provider_station_id == "42"
    assert observation.provider_channel_id == "7001"
    assert observation.observed_at == OBSERVED
    assert observation.provider_timestamp == "2026-09-13T19:15:00+02:00"
    assert observation.location.model_dump() == {"latitude": 32.1, "longitude": 34.8}
    assert observation.valid is True
    assert observation.provider_status == "Normal"
    assert observation.quality_policy == LIVE_QUALITY_POLICY
    assert "collected_at" not in AirQualityObservation.model_fields


def test_processor_uses_active_five_minute_lookup_and_preserves_order():
    service, lookup = processor()
    results = service.process_rows([row(11, 10.0), row(12, 21.0), row(13, 20.0)])

    assert [item.observation_id for item in results] == [11, 12, 13]
    assert [item.detector_status for item in results] == [
        "NORMAL", "SUSPECTED_ANOMALY", "NORMAL",
    ]
    assert [item.live_value for item in results] == [10.0, 21.0, 20.0]
    assert [item.baseline_p95 for item in results] == [20.0, 20.0, 20.0]
    assert len(lookup.requests) == 3
    assert all(
        request.identity.baseline_family == "five_minute_observation"
        for request in lookup.requests
    )


def test_invalid_persisted_observation_is_retained_as_not_evaluated():
    service, lookup = processor()
    invalid = row(
        12, 21.0,
        unit_source="metadata_fallback",
        measurement_unit=None,
        reading_unit=None,
    )

    results = service.process_rows([row(11, 10.0), invalid, row(13, 21.0)])

    assert [item.observation_id for item in results] == [11, 12, 13]
    assert [item.detector_status for item in results] == [
        "NORMAL", "NOT_EVALUATED", "SUSPECTED_ANOMALY",
    ]
    assert results[1].detector_reason == "measurement_unit_not_reading_supplied"
    assert results[1].baseline_p95 is None
    assert len(lookup.requests) == 2


def test_unavailable_active_baseline_is_not_evaluated_without_draft_fallback():
    lookup = UnavailableActiveLookup()
    service, _ = processor(lookup)

    result = service.process_rows([row(11, 21.0)])[0]

    assert result.detector_status == "NOT_EVALUATED"
    assert result.detector_reason == "baseline_unavailable"
    assert result.baseline_context.mode == "operational"
    assert result.baseline_context.reason == "no_active_version"
    assert lookup.requests[0].identity.baseline_family == "five_minute_observation"


def test_read_and_process_forwards_a_bounded_air_pollution_query():
    calls = []

    def reader(**kwargs):
        calls.append(kwargs)
        return [row(11, 10.0)]

    service, _ = processor(reader=reader)
    results = service.read_and_process(
        ingested_after=INGESTED,
        after_id=10,
        ingested_through=INGESTED,
        limit=25,
    )

    assert results[0].detector_status == "NORMAL"
    assert calls == [{
        "source": "air_pollution",
        "ingested_after": INGESTED,
        "after_id": 10,
        "ingested_through": INGESTED,
        "limit": 25,
    }]


def _bookmark_recorder(monkeypatch, *, since):
    from ecoguard.database.repositories import collector_runs

    finished = []
    monkeypatch.setattr(
        collector_runs,
        "last_success_at",
        lambda source: since if source == RUN_SOURCE else None,
    )
    monkeypatch.setattr(collector_runs, "log_start", lambda source: 91)
    monkeypatch.setattr(
        collector_runs,
        "log_finish",
        lambda run_id, **values: finished.append((run_id, values)),
    )
    return finished


def test_detect_new_turns_only_persisted_qualified_anomalies_into_signals(
    monkeypatch,
):
    calls = []

    def reader(**kwargs):
        calls.append(kwargs)
        return [row(11, 10.0), row(12, 21.0), row(13, 20.0)]

    service, _ = processor(reader=reader)
    since = INGESTED.replace(minute=0)
    finished = _bookmark_recorder(monkeypatch, since=since)

    signals = detect_new(processor=service, at=DETECTED)

    assert len(signals) == 1
    assert signals[0].hazard == AIR_POLLUTION
    assert signals[0].observed_at == OBSERVED
    assert signals[0].observed_at != INGESTED
    assert signals[0].value == 21.0
    assert signals[0].rarity is None
    assert signals[0].severity is None
    assert signals[0].confidence is None
    assert calls == [{
        "source": "air_pollution",
        "ingested_after": since,
        "after_id": 0,
        "ingested_through": DETECTED,
        "limit": 500,
    }]
    assert finished == [(91, {"status": "ok", "rows_written": 1})]


def test_detect_new_does_not_spatially_enrich_from_transport_configuration(monkeypatch):
    from ecoguard.detectors.air_pollution import observation_processing

    service, _ = processor(reader=lambda **_: [row(12, 21.0)])
    _bookmark_recorder(monkeypatch, since=INGESTED.replace(minute=0))
    calls = []

    class Enricher:
        def enrich_detection_result(self, result, *, radius_km):
            calls.append(radius_km)
            anomaly = result.anomaly
            return SpatiallyEnrichedAirPollutionAnomaly(
                anomaly=anomaly,
                spatial_context=PollutionSpatialContext(
                    location=anomaly.location,
                    lookup_radius_km=radius_km,
                    status="success",
                    source="OpenStreetMap / Overpass API",
                    collected_at=DETECTED,
                    provider_collection_status="success",
                    nearby_settlements=[NearbyGeographicFeature(
                        name="Real provider settlement",
                        osm_id=42,
                        osm_type="node",
                        latitude=32.11,
                        longitude=34.81,
                    )],
                ),
            )

    enricher = Enricher()
    monkeypatch.setattr(
        observation_processing,
        "AirPollutionSpatialEnricher",
        lambda: enricher,
    )
    monkeypatch.setenv("AIR_POLLUTION_TRANSPORT_SCREENING_ENABLED", "true")
    monkeypatch.setenv("AIR_POLLUTION_TRANSPORT_HALF_ANGLE_DEG", "45")
    monkeypatch.setenv("AIR_POLLUTION_TRANSPORT_MAX_DISTANCE_M", "10000")
    monkeypatch.setenv("AIR_POLLUTION_TRANSPORT_ARC_SEGMENT_COUNT", "8")
    monkeypatch.setenv("AIR_POLLUTION_WIND_MAX_AGE_MINUTES", "30")
    monkeypatch.setenv("AIR_POLLUTION_TRANSPORT_MIN_WIND_SPEED_MPS", "0.5")

    signals = detect_new(processor=service, at=DETECTED)

    assert calls == []
    context = signals[0].evidence["correlation_candidate"]["spatial_context"]
    assert context is None
    assert signals[0].evidence["detection_result"]["status"] == "SUSPECTED_ANOMALY"


def test_detect_new_normal_and_not_evaluated_results_emit_nothing(monkeypatch):
    unavailable = UnavailableActiveLookup()
    service, _ = processor(
        unavailable,
        reader=lambda **_: [row(11, 10.0), row(12, 21.0)],
    )
    finished = _bookmark_recorder(monkeypatch, since=INGESTED.replace(minute=0))

    assert detect_new(processor=service, at=DETECTED) == []
    assert finished == [(91, {"status": "ok", "rows_written": 0})]


def test_failed_processing_keeps_previous_bookmark_for_retry(monkeypatch):
    since = INGESTED.replace(minute=0)
    finished = _bookmark_recorder(monkeypatch, since=since)
    attempts = []

    def reader(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("temporary database failure")
        return [row(12, 21.0)]

    service, _ = processor(reader=reader)
    with pytest.raises(RuntimeError, match="temporary database failure"):
        detect_new(processor=service, at=DETECTED)

    signals = detect_new(processor=service, at=DETECTED)

    assert len(signals) == 1
    assert [attempt["ingested_after"] for attempt in attempts] == [since, since]
    assert finished[0][1]["status"] == "failed"
    assert finished[1] == (91, {"status": "ok", "rows_written": 1})


def test_detect_new_paginates_equal_ingestion_timestamps_by_id(monkeypatch):
    from ecoguard.detectors.air_pollution import observation_processing

    supplied = [row(11, 21.0), row(12, 10.0), row(13, 21.0)]
    calls = []

    def reader(**kwargs):
        calls.append(kwargs)
        after_id = kwargs["after_id"]
        return [item for item in supplied if item["id"] > after_id][
            : kwargs["limit"]
        ]

    monkeypatch.setattr(observation_processing, "DETECTION_BATCH_SIZE", 2)
    _bookmark_recorder(monkeypatch, since=INGESTED.replace(minute=0))
    service, _ = processor(reader=reader)

    signals = detect_new(processor=service, at=DETECTED)

    assert len(signals) == 2
    assert [call["after_id"] for call in calls] == [0, 12]
    assert all(call["ingested_after"] <= INGESTED for call in calls)


def test_first_run_starts_at_beginning_of_persisted_stream(monkeypatch):
    calls = []

    def reader(**kwargs):
        calls.append(kwargs)
        return []

    _bookmark_recorder(monkeypatch, since=None)
    service, _ = processor(reader=reader)

    assert detect_new(processor=service, at=DETECTED) == []
    assert calls[0]["ingested_after"] is None
    assert calls[0]["after_id"] is None
