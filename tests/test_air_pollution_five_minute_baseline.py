"""Offline tests for the five-minute cache-to-baseline pipeline."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from services.air_pollution_five_minute_baseline import (
    BASELINE_FAMILY,
    FiveMinuteBaselineError,
    build_profile,
)
from services.air_pollution_five_minute_baseline_validation import (
    validate_artifacts,
    validate_profile,
)


def point(timestamp, value=1.0, *, valid=True, unit="µg/m³", channel=4, pollutant="NO2"):
    return {
        "datetime": timestamp,
        "channels": [{
            "id": channel, "name": pollutant, "value": value, "status": 1,
            "valid": valid, "value_date": None, "units": unit, "PollutantId": 1,
        }],
    }


def cache_file(root, *, year, month, points=(), station="1", channel="4", pollutant="NO2"):
    folder = root / f"station_{station}" / f"channel_{channel}_{pollutant.lower().replace('.', '_')}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{year:04d}-{month:02d}.json.gz"
    payload = {
        "schema_version": "ecoguard-air-pollution-five-minute-cache-v1",
        "complete": True,
        "source": "Israel Ministry of Environmental Protection / Envista",
        "station_id": station,
        "station_name": "Station",
        "channel_id": channel,
        "pollutant": pollutant,
        "year": year,
        "month": month,
        "request_semantics": {
            "resolution": "provider five-minute averages", "timeBeginning": False,
            "quality_filter_applied": False, "unit_filter_applied": False,
            "off_grid_filter_applied": False,
        },
        "point_count": len(points),
        "points": list(points),
    }
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
    return path


def profile_files(root, points_by_month=None):
    points_by_month = points_by_month or {}
    return [
        cache_file(root, year=year, month=month, points=points_by_month.get((year, month), ()))
        for year in range(2021, 2026) for month in range(1, 13)
    ]


def bucket(profile, month=1, hour=1):
    return next(row for row in profile["buckets"] if row["month"] == month and row["hour"] == hour)


def test_exact_identity_unit_and_family_with_cache_unchanged(tmp_path):
    files = profile_files(tmp_path, {(2021, 1): [point("2021-01-01T01:00:00+02:00")]})
    before = {path: path.read_bytes() for path in files}
    profile = build_profile(files, minimum_samples=1, minimum_days=1, minimum_years=1)
    assert profile["baseline_family"] == BASELINE_FAMILY == "five_minute_observation"
    assert profile["identity"] == {
        "provider": "israel_ministry_environment_air_monitoring", "station_id": "1",
        "station_name": "Station", "channel_id": "4", "pollutant": "NO2",
        "canonical_unit": "µg/m³",
    }
    assert before == {path: path.read_bytes() for path in files}


def test_identity_mixing_is_refused(tmp_path):
    files = profile_files(tmp_path)
    files[-1] = cache_file(tmp_path, year=2025, month=12, station="2")
    with pytest.raises(FiveMinuteBaselineError, match="mix profile identities"):
        build_profile(files)


def test_quality_rejections_signed_values_and_last_accepted_duplicate(tmp_path):
    stamp = "2021-01-01T01:00:00+02:00"
    points = [
        point(stamp, -2.0), point(stamp, -1.0),
        point("2021-01-01T01:05:00+02:00", -9999, valid=True),
        point("2021-01-01T01:10:00+02:00", 3, valid=False),
        point("2021-01-01T01:15:00+02:00", float("inf")),
        point("2021-01-01T01:20:00+02:00", 4, unit=None),
        point("2021-01-01T01:25:00+02:00", 5, unit=None) | {"metadata_unit": "µg/m³"},
    ]
    profile = build_profile(profile_files(tmp_path, {(2021, 1): points}),
                            minimum_samples=1, minimum_days=1, minimum_years=1)
    result = bucket(profile)
    assert result["sample_count"] == 1 and result["mean"] == result["p95"] == -1.0
    audit = profile["quality_summary"]
    assert audit["duplicate_timestamp_revisions"] == 1
    assert audit["sentinel"] == audit["provider_invalid"] == 1
    assert audit["missing_malformed_or_nonfinite"] == 1
    assert audit["reading_unit_missing"] == 2


def test_off_grid_and_non_fixed_clock_are_rejected_not_snapped(tmp_path):
    points = [
        point("2021-01-01T01:03:00+02:00", 8),
        point("2021-01-01T01:05:00+03:00", 9),
        point("2021-01-01T01:10:00+02:00", 2),
    ]
    profile = build_profile(profile_files(tmp_path, {(2021, 1): points}),
                            minimum_samples=1, minimum_days=1, minimum_years=1)
    assert bucket(profile)["sample_count"] == 1
    assert profile["quality_summary"]["off_grid_timestamps"] == 1
    assert profile["quality_summary"]["wrong_provider_offset"] == 1


def test_raw_points_are_pooled_without_hourly_averaging_and_statistics_match(tmp_path):
    values = [1.0, 2.0, 3.0, 4.0]
    points = [point(f"2021-01-{day:02d}T01:00:00+02:00", value)
              for day, value in enumerate(values, start=1)]
    profile = build_profile(profile_files(tmp_path, {(2021, 1): points}),
                            minimum_samples=1, minimum_days=1, minimum_years=1)
    result = bucket(profile)
    assert result["sample_count"] == result["distinct_days"] == 4
    assert result["mean"] == result["median"] == 2.5
    assert result["std"] == pytest.approx(1.291, abs=0.0001)
    assert result["mad"] == 1.0
    assert [result[key] for key in ("p05", "p25", "p75", "p95")] == [1.15, 1.75, 3.25, 3.85]
    assert len(profile["buckets"]) == 288
    assert profile["aggregation"]["hourly_mean"] is False


def test_fixed_provider_hour_does_not_apply_dst(tmp_path):
    files = profile_files(tmp_path, {
        (2021, 1): [point("2021-01-01T04:00:00+02:00")],
        (2021, 7): [point("2021-07-01T04:00:00+02:00")],
    })
    profile = build_profile(files, minimum_samples=1, minimum_days=1, minimum_years=1)
    assert bucket(profile, 1, 4)["sample_count"] == 1
    assert bucket(profile, 7, 4)["sample_count"] == 1


def test_coverage_requires_samples_days_and_years(tmp_path):
    points_by_month = {}
    points = []
    for year in range(2021, 2024):
        yearly = []
        for day in range(1, 11):
            yearly.extend(point(f"{year}-01-{day:02d}T01:{minute:02d}:00+02:00") for minute in range(0, 45, 5))
        points_by_month[(year, 1)] = yearly
    profile = build_profile(profile_files(tmp_path, points_by_month))
    assert bucket(profile)["status"] == "ok"
    assert bucket(profile)["sample_count"] == 270
    assert bucket(profile)["distinct_days"] == 30
    assert bucket(profile)["distinct_years"] == 3
    assert profile["coverage_status"] == "PARTIAL_BASELINE"
    fewer = points_by_month.copy()
    fewer[(2023, 1)] = fewer[(2023, 1)][:-1]
    assert bucket(build_profile(profile_files(tmp_path / "less", fewer)))["status"] == "insufficient_history"


def test_full_classification_and_deterministic_profile(tmp_path):
    points_by_month = {}
    for month in range(1, 13):
        last = 28 if month == 2 else 30
        points_by_month[(2021, month)] = [
            point(f"2021-{month:02d}-{min(hour + 1, last):02d}T{hour:02d}:00:00+02:00")
            for hour in range(24)
        ]
    files = profile_files(tmp_path, points_by_month)
    first = build_profile(files, minimum_samples=1, minimum_days=1, minimum_years=1)
    second = build_profile(reversed(files), minimum_samples=1, minimum_days=1, minimum_years=1)
    assert first == second
    assert first["coverage_status"] == "FULL_BASELINE"
    assert first["coverage_summary"]["usable_buckets"] == 288


def test_artifact_validation_checks_family_and_cache_hashes(tmp_path):
    cache = tmp_path / "cache"
    files = profile_files(cache, {(2021, 1): [point("2021-01-01T01:00:00+02:00")]})
    profile = build_profile(files, minimum_samples=1, minimum_days=1, minimum_years=1)
    # Production validation requires the approved coverage policy, so restore
    # only coverage eligibility/status for this deliberately tiny fixture.
    for row in profile["buckets"]:
        row["status"] = "insufficient_history"
    profile["coverage_policy"] = {"minimum_distinct_years": 3, "minimum_distinct_days": 30, "minimum_samples": 270}
    profile["coverage_status"] = "INSUFFICIENT_HISTORY"
    profile["coverage_summary"] = {"usable_buckets": 0, "insufficient_buckets": 288, "total_buckets": 288}
    profiles = tmp_path / "artifacts" / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    result = validate_artifacts(profiles, cache_dir=cache, expected_profiles=1)
    assert result["validation"] == "PASS" and result["cache_checksums_verified"]
    profile["baseline_family"] = "completed_hour"
    assert validate_profile(profile)
