"""Dry-run adapter tests; no engine import or database access."""

from datetime import date

from services.air_pollution_five_minute_baseline_import import build_import_plan


def test_adapter_creates_only_draft_five_minute_identity(monkeypatch):
    identity = {
        "provider": "israel_ministry_environment_air_monitoring", "station_id": "1",
        "station_name": "Station", "channel_id": "4", "pollutant": "NO2",
        "canonical_unit": "µg/m³",
    }
    profile = {
        "identity": identity, "schema_version": "five-v1", "method_version": "method-v1",
        "source": {"name": "Ministry", "cache_schema": "ecoguard-air-pollution-five-minute-cache-v1"},
        "training_period": {"start": "2021-01-01", "end": "2025-12-31"},
        "aggregation_policy_version": "aggregation-v1", "quality_policy_version": "quality-v1",
        "coverage_status": "PARTIAL_BASELINE", "historical_units_observed": ["µg/m³"],
        "input_cache": {"profile_input_sha256": "b" * 64, "month_file_count": 60, "month_files": []},
        "time_semantics": {}, "aggregation": {}, "quality_policy": {}, "quality_summary": {},
        "limitations": ["limitation"], "coverage_policy": {}, "coverage_summary": {},
        "buckets": [{"month": 1, "hour": 0, "status": "ok", "sample_count": 270,
                     "distinct_days": 30, "distinct_years": 3, "years_present": [2021, 2022, 2023],
                     "mean": -1.0, "median": -1.0, "std": 0.0, "mad": 0.0,
                     "p05": -1.0, "p25": -1.0, "p75": -1.0, "p95": -1.0}],
    }
    monkeypatch.setattr(
        "services.air_pollution_five_minute_baseline_import.validate_artifacts",
        lambda *args, **kwargs: {"validation": "PASS", "errors": [],
            "status_counts": {"PARTIAL_BASELINE": 1}, "bucket_counts": {"total": 1, "ok": 1},
            "profiles": [{"profile": profile, "identity": tuple(identity.values()) + ("five_minute_observation",),
                          "content_sha256": "a" * 64}]},
    )
    monkeypatch.setattr(
        "services.air_pollution_five_minute_baseline_import.build_completed_hour_plan",
        lambda *args, **kwargs: {"station_catalog": [{"provider": identity["provider"], "station_id": "1"}],
                                 "catalog_content_sha256": "c" * 64},
    )
    plan = build_import_plan("unused", cache_dir="unused", completed_hour_source="unused",
                             expected_profiles=1, expected_stations=1)
    assert plan["dry_run"] is True and plan["imported_at"] is None
    assert plan["profiles"][0]["baseline_family"] == "five_minute_observation"
    assert plan["versions"][0]["lifecycle_status"] == "draft"
    assert plan["versions"][0]["generated_at"] is None
    assert plan["versions"][0]["training_start"] == date(2021, 1, 1)
    assert plan["buckets"][0]["mean"] == -1.0
    assert all(row["baseline_family"] != "completed_hour" for row in plan["profiles"])


def test_cli_keeps_double_write_guard_and_lazy_database_import():
    source = open("scripts/import_air_pollution_five_minute_baselines.py", encoding="utf-8").read()
    before, after = source.split("if args.write:", maxsplit=1)
    assert "ecoguard.database" not in before
    assert "--write" in before and "--confirm-write" in before
    assert "from ecoguard.database.repositories.air_pollution_baselines" in after
