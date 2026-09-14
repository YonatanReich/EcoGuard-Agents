from datetime import date, datetime, timezone

import pytest

from ecoguard.detectors.air_pollution.detector import AirPollutionAnomalyDetector
from ecoguard.detectors.air_pollution.baseline_schemas import (
    BaselineBucketStatistics,
    BaselineIdentity,
    BaselineVersionProvenance,
    LiveBaselineContextResult,
    LiveObservationContext,
)
from ecoguard.shared.air_quality_schemas import GeographicCoordinate

NOW = datetime(2026, 9, 13, 17, 15, tzinfo=timezone.utc)
DETECTED_AT = datetime(2026, 9, 13, 17, 16, tzinfo=timezone.utc)


def _live(value: float = 20.0) -> LiveObservationContext:
    return LiveObservationContext(
        provider="israel_ministry_environment_air_monitoring",
        station_id="42",
        channel_id="7001",
        pollutant="NO2",
        value=value,
        observed_at=NOW,
        provider_timestamp="2026-09-13 19:15:00",
        measurement_unit="ppb",
        unit_source="reading",
        reading_unit="ppb",
        location=GeographicCoordinate(latitude=32.1, longitude=34.8),
    )


def _identity(**changes) -> BaselineIdentity:
    values = {
        "provider": "israel_ministry_environment_air_monitoring",
        "station_id": "42",
        "channel_id": "7001",
        "pollutant": "NO2",
        "canonical_unit": "ppb",
        "baseline_family": "five_minute_observation",
    }
    values.update(changes)
    return BaselineIdentity(**values)


def _statistics(p95: float = 20.0, status: str = "ok") -> BaselineBucketStatistics:
    populated = status == "ok"
    return BaselineBucketStatistics(
        status=status,
        sample_count=150 if populated else 2,
        distinct_days=100 if populated else 1,
        distinct_years=5 if populated else 1,
        years_present=[2021, 2022, 2023, 2024, 2025] if populated else [2025],
        mean=8.0 if populated else None,
        median=7.0 if populated else None,
        std=3.0 if populated else None,
        mad=1.5 if populated else None,
        p05=2.0 if populated else None,
        p25=4.0 if populated else None,
        p75=12.0 if populated else None,
        p95=p95 if populated else None,
    )


def _version() -> BaselineVersionProvenance:
    return BaselineVersionProvenance(
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
        imported_at=DETECTED_AT,
        aggregation_policy_version="provider-five-minute-month-hour-v1",
        quality_policy_version="ecoguard-provider-valid-signed-v1",
        source_metadata={"official": True},
        aggregation_metadata={"bucket": "provider_month_hour"},
        quality_metadata={"signed_values": "preserved"},
        coverage_metadata={"qualifying_buckets": 288},
    )


def _context(
    *,
    value: float = 20.0,
    identity: BaselineIdentity | None = None,
    statistics: BaselineBucketStatistics | None = None,
) -> LiveBaselineContextResult:
    return LiveBaselineContextResult(
        status="available",
        reason="exact_baseline_available",
        mode="draft_validation",
        live_observation=_live(value),
        station_name="Central Station",
        lookup_identity=identity or _identity(),
        month=9,
        hour=19,
        lookup_status="available",
        baseline_statistics=statistics or _statistics(),
        baseline_version=_version(),
        comparison_eligible=True,
        eligibility_reason="exact_comparison_available",
    )


def _detector() -> AirPollutionAnomalyDetector:
    return AirPollutionAnomalyDetector(clock=lambda: DETECTED_AT)


@pytest.mark.parametrize("value", [19.99, 20.0])
def test_value_at_or_below_p95_is_normal_and_creates_no_anomaly(value):
    result = _detector().detect(_context(value=value))

    assert result.status == "NORMAL"
    assert result.anomaly is None


def test_value_above_p95_creates_canonical_anomaly_with_provenance():
    result = _detector().detect(_context(value=20.01))

    assert result.status == "SUSPECTED_ANOMALY"
    anomaly = result.anomaly
    assert anomaly.anomaly_type == "air_pollution"
    assert (anomaly.station_id, anomaly.channel_id, anomaly.pollutant) == (
        "42", "7001", "NO2"
    )
    assert anomaly.station_name == "Central Station"
    assert anomaly.unit == "ppb"
    assert anomaly.live_observation.provider_timestamp == "2026-09-13 19:15:00"
    assert anomaly.live_observation.unit_source == "reading"
    evidence = anomaly.baseline_evidence
    assert evidence.identity.baseline_family == "five_minute_observation"
    assert (evidence.month, evidence.hour) == (9, 19)
    assert evidence.statistics.p95 == 20.0
    assert evidence.statistics.median == 7.0
    assert evidence.statistics.mean == 8.0
    assert evidence.statistics.mad == 1.5
    assert evidence.version.baseline_version_id == 77
    assert evidence.version.content_sha256 == "a" * 64
    assert evidence.version.quality_policy_version == "ecoguard-provider-valid-signed-v1"
    assert evidence.version.aggregation_policy_version == "provider-five-minute-month-hour-v1"


@pytest.mark.parametrize(
    ("status", "expected_reason"),
    [
        ("baseline_unavailable", "baseline_unavailable"),
        ("profile_unavailable", "baseline_unavailable"),
        ("bucket_unavailable", "baseline_unavailable"),
        ("insufficient_history", "insufficient_history"),
    ],
)
def test_unavailable_or_insufficient_context_is_not_evaluated(status, expected_reason):
    result = _detector().detect(
        LiveBaselineContextResult(
            status=status,
            reason=status,
            mode="operational",
            comparison_eligible=False,
            eligibility_reason=status,
        )
    )

    assert result.status == "NOT_EVALUATED"
    assert result.reason == expected_reason
    assert result.anomaly is None


def test_invalid_live_observation_is_not_evaluated_and_creates_no_anomaly():
    context = LiveBaselineContextResult(
        status="invalid_live_observation",
        reason="missing_reading_unit",
        mode="operational",
        comparison_eligible=False,
        eligibility_reason="missing_reading_unit",
    )

    result = _detector().detect(context)

    assert result.status == "NOT_EVALUATED"
    assert result.reason == "missing_reading_unit"
    assert result.anomaly is None


@pytest.mark.parametrize(
    "identity",
    [
        _identity(canonical_unit="µg/m³"),
        _identity(station_id="other-station"),
        _identity(channel_id="other-channel"),
        _identity(pollutant="O3"),
    ],
)
def test_identity_or_unit_mismatch_never_falls_back(identity):
    result = _detector().detect(_context(value=100.0, identity=identity))

    assert result.status == "NOT_EVALUATED"
    assert result.reason in {"identity_mismatch", "unit_mismatch"}
    assert result.anomaly is None


def test_completed_hour_baseline_is_never_used_as_fallback():
    result = _detector().detect(
        _context(
            value=100.0,
            identity=_identity(baseline_family="completed_hour"),
        )
    )

    assert result.status == "NOT_EVALUATED"
    assert result.reason == "baseline_family_mismatch"
    assert result.anomaly is None


def test_provider_valid_signed_reading_is_evaluated_without_clipping():
    result = _detector().detect(
        _context(value=-1.0, statistics=_statistics(p95=-2.0))
    )

    assert result.status == "SUSPECTED_ANOMALY"
    assert result.anomaly.value == -1.0
    assert result.anomaly.baseline_evidence.statistics.p95 == -2.0
