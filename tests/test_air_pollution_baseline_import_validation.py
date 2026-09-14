"""Synthetic offline contract tests; no provider access or baseline generation."""
import copy
import csv
import hashlib
import json

import pytest

from services.air_pollution_baseline_import_validation import (
    SCHEMA, TIME_RULE, build_manifest, validate_profile,
)


@pytest.fixture
def profile():
    return {
        "station": {"id": 1, "name": "test station"}, "channel_id": 4,
        "pollutant": "NO2", "historical_unit": "µg/m³", "metadata_unit": "ppb",
        "historical_units_observed": ["µg/m³"], "schema_version": SCHEMA,
        "source": "Israel Ministry of Environmental Protection / Envista",
        "training_period": {"start_year": 2021, "end_year": 2025},
        "time_semantics": {"rule": TIME_RULE}, "profile_status": "ok",
        "hourly_aggregation": {"source_resolution_minutes": 5, "min_valid_points_per_hour": 9,
                               "method": "arithmetic_mean_of_valid_unique_measurements"},
        "coverage_policy": {"min_distinct_years_per_bucket": 3, "min_distinct_days_per_bucket": 30},
        "quality_summary": {"accepted_hourly_values": 288 * 30},
        "coverage_summary": {"ok_buckets": 288, "total_buckets": 288, "ok_percent": 100.0},
        "buckets": [{"month": m, "hour": h, "status": "ok", "hourly_sample_count": 30,
                     "distinct_day_count": 30, "distinct_year_count": 3, "years_present": [2021, 2022, 2023],
                     "mean": 1, "median": 1, "std": 2, "mad": 1, "p05": -1, "p25": 0, "p75": 2, "p95": 3}
                    for m in range(1, 13) for h in range(24)],
    }


def test_valid_and_unchanged(profile):
    original = copy.deepcopy(profile)
    assert validate_profile(profile) == []
    assert profile == original  # negatives are not clipped


@pytest.mark.parametrize("key,value", [
    ("station", {}), ("channel_id", True), ("pollutant", "PM25"),
    ("historical_unit", None), ("historical_units_observed", ["ppb", "µg/m³"]),
    ("schema_version", "old"), ("training_period", {}), ("hourly_aggregation", {}),
    ("coverage_policy", {}), ("time_semantics", {}), ("buckets", None),
    ("profile_status", "partial_coverage"),
])
def test_invalid_profile_fields(profile, key, value):
    profile[key] = value
    assert validate_profile(profile)


@pytest.mark.parametrize("key,value", [
    ("month", 13), ("hour", True), ("hourly_sample_count", -1),
    ("distinct_day_count", 31), ("distinct_year_count", 2), ("years_present", [2020, 2022, 2023]),
    ("status", "normal"), ("mean", float("nan")), ("median", None),
    ("std", -1), ("mad", -1), ("p05", 9), ("p25", 9), ("p75", -9), ("p95", float("inf")),
])
def test_invalid_bucket_fields(profile, key, value):
    profile["buckets"][0][key] = value
    assert validate_profile(profile)


def test_missing_duplicate_and_partial(profile):
    profile["buckets"][0] = copy.deepcopy(profile["buckets"][1])
    assert any("duplicate" in e for e in validate_profile(profile))
    profile["buckets"].pop()
    assert any("missing=" in e for e in validate_profile(profile))


def test_empty_bucket_partial(profile):
    b = profile["buckets"][0]
    b.clear()
    b.update(month=1, hour=0, status="insufficient_history", hourly_sample_count=0,
             distinct_day_count=0, distinct_year_count=0, years_present=[])
    profile["profile_status"] = "partial_coverage"
    profile["coverage_summary"].update(ok_buckets=287, ok_percent=round(287/288*100, 2))
    profile["quality_summary"]["accepted_hourly_values"] -= 30
    assert validate_profile(profile) == []
    b["mean"] = 0  # do not invent stats for missing history
    assert validate_profile(profile)


def make_files(tmp_path, profile):
    folder = tmp_path / "profiles"
    folder.mkdir()
    path = folder / "one.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    catalog = tmp_path / "catalog.csv"
    with catalog.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["station_id", "station_name", "pollutant", "status", "channels", "unit", "reason"])
        writer.writeheader()
        for pol in ("NO2", "O3", "PM10", "PM2.5", "SO2"):
            writer.writerow(dict(station_id=1, station_name="test station", pollutant=pol,
                                 status="FULL_BASELINE" if pol == "NO2" else "NOT_MEASURED",
                                 channels="4" if pol == "NO2" else "", unit="µg/m³" if pol == "NO2" else "", reason=""))
    return folder, catalog


def test_manifest_deterministic_readonly(profile, tmp_path, monkeypatch):
    folder, catalog = make_files(tmp_path, profile)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setenv("DATABASE_URL", "DO-NOT-READ-OR-EXPOSE")
    a = build_manifest(folder, catalog, expected_profiles=1, expected_stations=1)
    assert a == build_manifest(folder, catalog, expected_profiles=1, expected_stations=1)
    assert a["errors"] == []
    assert a["row_counts"]["baseline_buckets"] == 288
    assert a["versions"][0]["content_sha256"] == hashlib.sha256(before[folder / "one.json"]).hexdigest()
    assert a["versions"][0]["generated_at"] is None
    assert a["versions"][0]["imported_at"] is None
    assert a["negative_profiles"][0]["fields"]["p05"][0]["value"] == -1
    assert not a["activation_allowed"]
    assert a["operational_import_readiness"] == "PASS"
    assert a["blockers"] == []
    from services.air_pollution_hourly import AGGREGATION_POLICY
    from services.air_quality_schemas import LIVE_QUALITY_POLICY
    assert a["compatibility_contract"]["aggregation_policy"] == AGGREGATION_POLICY
    assert a["compatibility_contract"]["quality_policy"] == LIVE_QUALITY_POLICY
    assert "DO-NOT-READ-OR-EXPOSE" not in json.dumps(a)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_duplicates_and_bad_json(profile, tmp_path):
    folder, catalog = make_files(tmp_path, profile)
    (folder / "two.json").write_text(json.dumps(profile), encoding="utf-8")
    a = build_manifest(folder, catalog, expected_profiles=2, expected_stations=1)
    assert any("duplicate identity" in e for e in a["errors"])
    (folder / "two.json").write_text('{"x":1,"x":2}', encoding="utf-8")
    a = build_manifest(folder, catalog, expected_profiles=2, expected_stations=1)
    assert any("malformed" in e for e in a["errors"])


def test_channel_conflict(profile, tmp_path):
    folder, catalog = make_files(tmp_path, profile)
    profile["pollutant"] = "SO2"
    (folder / "two.json").write_text(json.dumps(profile), encoding="utf-8")
    a = build_manifest(folder, catalog, expected_profiles=2, expected_stations=1)
    assert any("channel conflict" in e for e in a["errors"])
