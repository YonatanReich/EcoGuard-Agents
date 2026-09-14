from datetime import date, datetime, timezone

import pytest

from ecoguard.detectors.air_pollution.baseline_lookup import AirPollutionBaselineLookupService
from ecoguard.detectors.air_pollution.baseline_schemas import BaselineIdentity


IDENTITY = {
    "provider": "israel_ministry_environment_air_monitoring",
    "station_id": "1",
    "channel_id": "4",
    "pollutant": "NO2",
    "canonical_unit": "µg/m³",
    "baseline_family": "completed_hour",
}


def row(*, lifecycle="active", bucket_status="ok", bucket=True, version=True,
        profile=True):
    result = {
        "station_name": "Pilot station",
        "catalog_availability": [{"pollutant": "NO2", "status": "FULL_BASELINE"}],
        "profile_id": 10 if profile else None,
        "baseline_version_id": 20 if version else None,
        "parent_version_id": None,
        "content_sha256": "b" * 64,
        "schema_version": "air-pollution-national-baseline-v2",
        "method_version": "national-v2",
        "source_name": "Israeli Ministry historical export",
        "source_version": "2021-2025",
        "training_start": date(2021, 1, 1),
        "training_end": date(2025, 12, 31),
        "imported_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "generated_at": None,
        "aggregation_policy_version": "national-v2-last-accepted-hourly-v1",
        "quality_policy_version": "provider-valid-signed-v1",
        "coverage_status": "FULL_BASELINE",
        "lifecycle_status": lifecycle,
        "source_metadata": {"authority": "Ministry"},
        "aggregation_metadata": {"minimum_slots": 9},
        "quality_metadata": {"signed_values": True},
        "coverage_metadata": {"qualifying_buckets": 288},
        "bucket_id": 30 if bucket else None,
        "bucket_status": bucket_status if bucket else None,
        "sample_count": 100 if bucket else None,
        "distinct_days": 80 if bucket else None,
        "distinct_years": 5 if bucket else None,
        "years_present": [2021, 2022, 2023, 2024, 2025] if bucket else None,
        "mean": 21.0 if bucket else None,
        "median": 20.0 if bucket else None,
        "std": 4.0 if bucket else None,
        "mad": 2.0 if bucket else None,
        "p05": 14.0 if bucket else None,
        "p25": 18.0 if bucket else None,
        "p75": 23.0 if bucket else None,
        "p95": 29.0 if bucket else None,
    }
    if not version:
        for key in (
            "parent_version_id", "content_sha256", "schema_version", "method_version",
            "source_name", "source_version", "training_start", "training_end",
            "imported_at", "generated_at", "aggregation_policy_version",
            "quality_policy_version", "coverage_status", "lifecycle_status",
            "source_metadata", "aggregation_metadata", "quality_metadata",
            "coverage_metadata", "bucket_id", "bucket_status", "sample_count",
            "distinct_days", "distinct_years", "years_present", "mean", "median",
            "std", "mad", "p05", "p25", "p75", "p95",
        ):
            result[key] = None
    return result


class RecordingReader:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


class RecordingBatchReader:
    def __init__(self, rows_for_request):
        self.rows_for_request = rows_for_request
        self.calls = []

    def __call__(self, *, requests, lifecycle_status):
        self.calls.append((requests, lifecycle_status))
        rows = []
        for request in requests:
            selected = self.rows_for_request(request)
            rows.extend({**item, "request_index": request["request_index"]}
                        for item in selected)
        return rows


def test_exact_active_lookup_returns_statistics_and_provenance():
    reader = RecordingReader([row()])
    result = AirPollutionBaselineLookupService(reader).lookup(
        IDENTITY, month=7, hour=14,
    )

    assert result.status == "available"
    assert result.reason == "exact_baseline_available"
    assert result.bucket.mean == 21.0
    assert result.bucket.years_present == [2021, 2022, 2023, 2024, 2025]
    assert result.version.baseline_version_id == 20
    assert result.version.content_sha256 == "b" * 64
    assert result.version.coverage_status == "FULL_BASELINE"
    assert result.version.lifecycle_status == "active"
    assert reader.calls == [{**IDENTITY, "month": 7, "hour": 14,
                             "lifecycle_status": "active",
                             "baseline_version_id": None}]


@pytest.mark.parametrize("field,value,rows", [
    ("station_id", "999", []),
    ("channel_id", "other", [row(profile=False)]),
    ("pollutant", "O3", [row(profile=False)]),
    ("canonical_unit", "ppb", [row(profile=False)]),
    ("baseline_family", "five_minute_observation", [row(profile=False)]),
])
def test_wrong_identity_is_unavailable_without_substitution(field, value, rows):
    identity = {**IDENTITY, field: value}
    reader = RecordingReader(rows)

    result = AirPollutionBaselineLookupService(reader).lookup(
        identity, month=7, hour=14,
    )

    assert result.status == "profile_unavailable"
    assert len(reader.calls) == 1
    assert reader.calls[0][field] == value
    assert reader.calls[0]["month"] == 7
    assert reader.calls[0]["hour"] == 14


def test_missing_exact_bucket_is_explicitly_unavailable():
    result = AirPollutionBaselineLookupService(
        RecordingReader([row(bucket=False)])
    ).lookup(IDENTITY, month=2, hour=3)

    assert result.status == "bucket_unavailable"
    assert result.reason == "exact_month_hour_bucket_not_found"
    assert result.version.baseline_version_id == 20
    assert result.bucket is None


def test_insufficient_history_is_not_reported_as_available():
    result = AirPollutionBaselineLookupService(
        RecordingReader([row(bucket_status="insufficient_history")])
    ).lookup(IDENTITY, month=2, hour=3)

    assert result.status == "insufficient_history"
    assert result.reason == "exact_bucket_insufficient_history"
    assert result.bucket.status == "insufficient_history"


def test_draft_is_excluded_from_default_operational_lookup():
    reader = RecordingReader([row(version=False)])
    result = AirPollutionBaselineLookupService(reader).lookup(
        IDENTITY, month=2, hour=3,
    )

    assert result.status == "baseline_unavailable"
    assert result.reason == "no_active_version"
    assert reader.calls[0]["lifecycle_status"] == "active"


def test_explicit_draft_validation_lookup_works():
    reader = RecordingReader([row(lifecycle="draft")])
    result = AirPollutionBaselineLookupService(reader).lookup_draft_for_validation(
        BaselineIdentity(**IDENTITY), month=2, hour=3, baseline_version_id=20,
    )

    assert result.status == "available"
    assert result.mode == "draft_validation"
    assert result.version.lifecycle_status == "draft"
    assert reader.calls[0]["lifecycle_status"] == "draft"
    assert reader.calls[0]["baseline_version_id"] == 20


def test_operational_lookup_requires_active_even_when_draft_exists():
    def lifecycle_reader(**kwargs):
        assert kwargs["lifecycle_status"] == "active"
        return [row(lifecycle="active")]

    result = AirPollutionBaselineLookupService(lifecycle_reader).lookup(
        IDENTITY, month=2, hour=3,
    )

    assert result.status == "available"
    assert result.version.lifecycle_status == "active"


def test_ambiguous_drafts_fail_closed_without_version_id():
    second = row(lifecycle="draft")
    second["baseline_version_id"] = 21
    result = AirPollutionBaselineLookupService(
        RecordingReader([row(lifecycle="draft"), second])
    ).lookup_draft_for_validation(IDENTITY, month=2, hour=3)

    assert result.status == "baseline_unavailable"
    assert result.reason == "ambiguous_draft_versions"


def test_invalid_identity_does_not_query_repository():
    reader = RecordingReader([])
    result = AirPollutionBaselineLookupService(reader).lookup(
        {**IDENTITY, "channel_id": ""}, month=13, hour=3,
    )

    assert result.status == "invalid_identity"
    assert reader.calls == []


def test_lookup_requires_family_and_rejects_unknown_family():
    reader = RecordingReader([])
    without_family = {key: value for key, value in IDENTITY.items()
                      if key != "baseline_family"}
    assert AirPollutionBaselineLookupService(reader).lookup(
        without_family, month=1, hour=0,
    ).status == "invalid_identity"
    assert AirPollutionBaselineLookupService(reader).lookup(
        {**IDENTITY, "baseline_family": "hourly"}, month=1, hour=0,
    ).status == "invalid_identity"
    assert reader.calls == []


def test_batch_matches_single_results_and_preserves_duplicates_and_order():
    requests = [
        {"identity": IDENTITY, "month": 7, "hour": 14},
        {"identity": {**IDENTITY, "station_id": "missing"}, "month": 7, "hour": 14},
        {"identity": IDENTITY, "month": 7, "hour": 14},
    ]

    def selected(request):
        return [] if request["station_id"] == "missing" else [row()]

    batch_reader = RecordingBatchReader(selected)
    service = AirPollutionBaselineLookupService(
        RecordingReader([row()]), batch_reader=batch_reader,
    )
    actual = service.lookup_batch(requests)
    expected = [
        AirPollutionBaselineLookupService(RecordingReader([row()])).lookup(
            IDENTITY, month=7, hour=14,
        ),
        AirPollutionBaselineLookupService(RecordingReader([])).lookup(
            {**IDENTITY, "station_id": "missing"}, month=7, hour=14,
        ),
        AirPollutionBaselineLookupService(RecordingReader([row()])).lookup(
            IDENTITY, month=7, hour=14,
        ),
    ]

    assert actual == expected
    assert len(actual) == 3
    assert len(batch_reader.calls) == 1
    assert len(batch_reader.calls[0][0]) == 3
    assert batch_reader.calls[0][1] == "active"


def test_batch_preserves_insufficient_and_exact_identity_failures_without_fallback():
    requests = [
        {"identity": IDENTITY, "month": 2, "hour": 3},
        {"identity": {**IDENTITY, "channel_id": "wrong"}, "month": 2, "hour": 3},
        {"identity": {**IDENTITY, "canonical_unit": "ppb"}, "month": 2, "hour": 3},
        {"identity": {**IDENTITY, "baseline_family": "five_minute_observation"},
         "month": 2, "hour": 3},
    ]

    def selected(request):
        if request["channel_id"] == IDENTITY["channel_id"] and request[
            "canonical_unit"
        ] == IDENTITY["canonical_unit"] and request["baseline_family"] == "completed_hour":
            return [row(bucket_status="insufficient_history")]
        return [row(profile=False)]

    reader = RecordingBatchReader(selected)
    results = AirPollutionBaselineLookupService(
        batch_reader=reader,
    ).lookup_batch(requests)

    assert [item.status for item in results] == [
        "insufficient_history", "profile_unavailable",
        "profile_unavailable", "profile_unavailable",
    ]
    passed = reader.calls[0][0]
    assert passed[1]["channel_id"] == "wrong"
    assert passed[2]["canonical_unit"] == "ppb"
    assert passed[3]["baseline_family"] == "five_minute_observation"


def test_draft_batch_is_explicit_and_draft_only():
    reader = RecordingBatchReader(lambda request: [row(lifecycle="draft")])
    service = AirPollutionBaselineLookupService(batch_reader=reader)

    result = service.lookup_draft_batch_for_validation([
        {"identity": IDENTITY, "month": 2, "hour": 3,
         "baseline_version_id": 20},
    ])

    assert result[0].status == "available"
    assert result[0].mode == "draft_validation"
    assert result[0].version.lifecycle_status == "draft"
    assert reader.calls[0][1] == "draft"
    assert reader.calls[0][0][0]["baseline_version_id"] == 20


def test_invalid_batch_item_is_retained_without_repository_request():
    reader = RecordingBatchReader(lambda request: [row()])
    results = AirPollutionBaselineLookupService(batch_reader=reader).lookup_batch([
        {"identity": {**IDENTITY, "channel_id": ""}, "month": 2, "hour": 3},
        {"identity": IDENTITY, "month": 2, "hour": 3},
    ])

    assert [item.status for item in results] == ["invalid_identity", "available"]
    assert len(reader.calls[0][0]) == 1
    assert reader.calls[0][0][0]["request_index"] == 1
