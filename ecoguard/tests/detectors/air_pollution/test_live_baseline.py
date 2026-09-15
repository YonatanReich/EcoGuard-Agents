from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from ecoguard.detectors.air_pollution.baseline_schemas import (
    BaselineBucketStatistics,
    BaselineLookupResult,
    BaselineVersionProvenance,
)
from ecoguard.detectors.air_pollution.live_baseline import AirPollutionLiveBaselineContextService
from ecoguard.shared.air_quality_schemas import AirQualityObservation, LIVE_QUALITY_POLICY


def live(**changes):
    data = {
        "provider_station_id": "17",
        "provider_channel_id": "101",
        "location": {"latitude": 32.1, "longitude": 34.8},
        "pollutant": "NO2",
        "value": 12.5,
        "unit": "ppb",
        "provider_unit": "ppb",
        "measurement_unit": "ppb",
        "reading_unit": "ppb",
        "metadata_unit": "µg/m³",
        "unit_source": "reading",
        "quality_policy": LIVE_QUALITY_POLICY,
        "observed_at": "2026-07-31T22:15:00Z",
        "provider_timestamp": "2026-08-01T00:15:00+02:00",
        "valid": True,
    }
    data.update(changes)
    return data


def version(lifecycle):
    return BaselineVersionProvenance(
        baseline_version_id=20,
        content_sha256="c" * 64,
        coverage_status="FULL_BASELINE",
        lifecycle_status=lifecycle,
        schema_version="air-pollution-national-baseline-v2",
        source_name="Ministry",
        training_start=date(2021, 1, 1),
        training_end=date(2025, 12, 31),
        imported_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        aggregation_policy_version="historical-hourly-v1",
        quality_policy_version="historical-valid-signed-v1",
        source_metadata={},
        aggregation_metadata={},
        quality_metadata={},
        coverage_metadata={},
    )


def lookup_result(identity, *, status="available", lifecycle="active"):
    bucket = BaselineBucketStatistics(
        status="insufficient_history" if status == "insufficient_history" else "ok",
        sample_count=0 if status == "insufficient_history" else 100,
        distinct_days=0 if status == "insufficient_history" else 80,
        distinct_years=0 if status == "insufficient_history" else 5,
        years_present=[] if status == "insufficient_history" else [2021, 2022, 2023, 2024, 2025],
        mean=None if status == "insufficient_history" else 10.0,
        median=None if status == "insufficient_history" else 9.0,
        std=None if status == "insufficient_history" else 2.0,
        mad=None if status == "insufficient_history" else 1.0,
        p05=None if status == "insufficient_history" else 6.0,
        p25=None if status == "insufficient_history" else 8.0,
        p75=None if status == "insufficient_history" else 11.0,
        p95=None if status == "insufficient_history" else 14.0,
    ) if status in {"available", "insufficient_history"} else None
    reason = {
        "available": "exact_baseline_available",
        "insufficient_history": "exact_bucket_insufficient_history",
        "baseline_unavailable": "no_active_version",
        "profile_unavailable": "exact_profile_not_found",
    }[status]
    return BaselineLookupResult(
        status=status,
        reason=reason,
        mode="draft_validation" if lifecycle == "draft" else "operational",
        identity=identity,
        month=8,
        hour=0,
        version=version(lifecycle) if bucket else None,
        bucket=bucket,
    )


class Lookup:
    def __init__(self, status="available"):
        self.status = status
        self.calls = []

    def lookup(self, identity, *, month, hour):
        self.calls.append(("active", identity, month, hour, None))
        return lookup_result(identity, status=self.status, lifecycle="active")

    def lookup_draft_for_validation(self, identity, *, month, hour,
                                    baseline_version_id=None):
        self.calls.append(("draft", identity, month, hour, baseline_version_id))
        return lookup_result(identity, status=self.status, lifecycle="draft")


class BatchLookup(Lookup):
    def lookup_batch(self, requests):
        self.calls.append(("active_batch", list(requests)))
        return [lookup_result(item.identity, status=self.status, lifecycle="active")
                for item in self.calls[-1][1]]

    def lookup_draft_batch_for_validation(self, requests):
        self.calls.append(("draft_batch", list(requests)))
        return [lookup_result(item.identity, status=self.status, lifecycle="draft")
                for item in self.calls[-1][1]]


def test_live_observation_resolves_exact_identity_and_provider_hour():
    lookup = Lookup()
    result = AirPollutionLiveBaselineContextService(lookup).lookup(live())

    assert result.status == "available"
    assert result.lookup_identity.model_dump() == {
        "provider": "israel_ministry_environment_air_monitoring",
        "station_id": "17",
        "channel_id": "101",
        "pollutant": "NO2",
        "canonical_unit": "ppb",
        "baseline_family": "five_minute_observation",
    }
    assert (result.month, result.hour) == (8, 0)
    assert lookup.calls[0][0] == "active"
    assert lookup.calls[0][1].baseline_family == "five_minute_observation"
    assert result.baseline_statistics.mean == 10.0
    assert result.comparison_eligible is True
    assert result.eligibility_reason == "exact_baseline_available"


@pytest.mark.parametrize("changes,reason", [
    ({"provider_channel_id": ""}, "missing_channel_id"),
    ({"provider_channel_id": None}, "missing_channel_id"),
    ({"unit_source": "metadata_fallback", "measurement_unit": None,
      "reading_unit": None}, "measurement_unit_not_reading_supplied"),
    ({"measurement_unit": None}, "missing_measurement_unit_provenance"),
    ({"reading_unit": None}, "missing_measurement_unit_provenance"),
    ({"unit": "µg/m³"}, "incompatible_measurement_unit"),
    ({"pollutant": "CO"}, "unsupported_baseline_pollutant"),
    ({"provider_timestamp": "2026-08-01T01:15:00+03:00"},
     "provider_clock_incompatible"),
])
def test_ineligible_live_identity_never_queries(changes, reason):
    lookup = Lookup()
    result = AirPollutionLiveBaselineContextService(lookup).lookup(
        {**live(), **changes},
    )

    assert result.status == "invalid_live_observation"
    assert result.reason == reason
    assert lookup.calls == []


@pytest.mark.parametrize("status", ["baseline_unavailable", "profile_unavailable"])
def test_baseline_unavailability_is_preserved(status):
    result = AirPollutionLiveBaselineContextService(Lookup(status)).lookup(live())

    assert result.status == status
    assert result.comparison_eligible is False
    assert result.eligibility_reason in {"no_active_version", "exact_profile_not_found"}


def test_missing_five_minute_family_does_not_fallback_to_completed_hour():
    lookup = Lookup("profile_unavailable")
    result = AirPollutionLiveBaselineContextService(lookup).lookup_draft_for_validation(
        live(),
    )
    assert result.status == "profile_unavailable"
    assert result.lookup_identity.baseline_family == "five_minute_observation"
    assert lookup.calls == [("draft", result.lookup_identity, 8, 0, None)]


def test_insufficient_history_is_preserved():
    result = AirPollutionLiveBaselineContextService(
        Lookup("insufficient_history")
    ).lookup(live())

    assert result.status == "insufficient_history"
    assert result.baseline_statistics.status == "insufficient_history"
    assert result.eligibility_reason == "exact_bucket_insufficient_history"


def test_draft_requires_explicit_validation_method():
    lookup = Lookup()
    service = AirPollutionLiveBaselineContextService(lookup)

    operational = service.lookup(AirQualityObservation(**live()))
    validation = service.lookup_draft_for_validation(
        AirQualityObservation(**live()), baseline_version_id=20,
    )

    assert operational.mode == "operational"
    assert validation.mode == "draft_validation"
    assert [call[0] for call in lookup.calls] == ["active", "draft"]
    assert lookup.calls[1][4] == 20
    assert validation.baseline_version.lifecycle_status == "draft"


@pytest.mark.parametrize("changes,expected", [
    ({"provider_station_id": "999"}, ("999", "101", "NO2", "ppb", 8, 0)),
    ({"provider_channel_id": "999"}, ("17", "999", "NO2", "ppb", 8, 0)),
    ({"pollutant": "O3"}, ("17", "101", "O3", "ppb", 8, 0)),
    ({"unit": "µg/m³", "provider_unit": "µg/m³",
      "measurement_unit": "µg/m³", "reading_unit": "µg/m³"},
     ("17", "101", "NO2", "µg/m³", 8, 0)),
    ({"observed_at": "2026-08-01T00:15:00Z",
      "provider_timestamp": "2026-08-01T02:15:00+02:00"},
     ("17", "101", "NO2", "ppb", 8, 2)),
])
def test_exact_dimensions_are_passed_without_fallback(changes, expected):
    lookup = Lookup("profile_unavailable")
    item = live(**changes)
    result = AirPollutionLiveBaselineContextService(lookup).lookup(item)

    assert result.status == "profile_unavailable"
    _, identity, month, hour, version_id = lookup.calls[0]
    assert (
        identity.station_id, identity.channel_id, identity.pollutant,
        identity.canonical_unit, month, hour,
    ) == expected
    assert version_id is None


def test_adapter_does_not_mutate_live_mapping():
    item = live()
    original = deepcopy(item)
    AirPollutionLiveBaselineContextService(Lookup()).lookup(item)
    assert item == original


@pytest.mark.parametrize("status", [
    "available", "profile_unavailable", "baseline_unavailable",
    "insufficient_history",
])
def test_live_batch_is_semantically_identical_to_single_lookup(status):
    observations = [live(value=10.0), live(value=11.0)]
    singles = [
        AirPollutionLiveBaselineContextService(Lookup(status)).lookup(item)
        for item in observations
    ]
    batch_lookup = BatchLookup(status)
    batch = AirPollutionLiveBaselineContextService(batch_lookup).lookup_batch(observations)

    assert batch == singles
    assert len(batch_lookup.calls) == 1
    assert batch_lookup.calls[0][0] == "active_batch"


def test_live_batch_retains_invalid_items_and_does_not_drop_duplicates():
    observations = [
        live(value=10.0),
        live(provider_channel_id=""),
        live(value=10.0),
    ]
    lookup = BatchLookup()
    results = AirPollutionLiveBaselineContextService(lookup).lookup_batch(observations)

    assert len(results) == len(observations)
    assert [item.status for item in results] == [
        "available", "invalid_live_observation", "available",
    ]
    assert len(lookup.calls[0][1]) == 2


def test_live_draft_batch_explicitly_uses_five_minute_family_only():
    lookup = BatchLookup("profile_unavailable")
    result = AirPollutionLiveBaselineContextService(
        lookup
    ).lookup_draft_batch_for_validation([live()])

    assert result[0].mode == "draft_validation"
    assert result[0].status == "profile_unavailable"
    assert lookup.calls[0][0] == "draft_batch"
    assert lookup.calls[0][1][0].identity.baseline_family == "five_minute_observation"
