"""Pure artifact adapter tests; no SQLAlchemy engine, DB or network."""

import csv
import hashlib
import json

import pytest

from services.air_pollution_baseline_import import (
    HISTORICAL_AGGREGATION_POLICY, HISTORICAL_BASELINE_FAMILY,
    HISTORICAL_QUALITY_POLICY, build_import_plan,
)
from services.air_pollution_baseline_import_validation import SCHEMA, TIME_RULE
from services.air_quality_schemas import MINISTRY_PROVIDER_ID


def artifacts(tmp_path):
    root = tmp_path / "source"
    profiles = root / "profiles"
    profiles.mkdir(parents=True)
    profile = {
        "station": {"id": 1, "name": "Station"}, "channel_id": 4,
        "pollutant": "NO2", "historical_unit": "µg/m³", "metadata_unit": "ppb",
        "historical_units_observed": ["µg/m³"], "monitor_active_metadata": True,
        "schema_version": SCHEMA, "source": "Israel Ministry of Environmental Protection / Envista",
        "training_period": {"start_year": 2021, "end_year": 2025},
        "time_semantics": {"rule": TIME_RULE}, "profile_status": "ok",
        "hourly_aggregation": {"source_resolution_minutes": 5,
                               "method": "arithmetic_mean_of_valid_unique_measurements",
                               "min_valid_points_per_hour": 9},
        "coverage_policy": {"min_distinct_years_per_bucket": 3,
                            "min_distinct_days_per_bucket": 30},
        "quality_summary": {"accepted_hourly_values": 8640},
        "coverage_summary": {"ok_buckets": 288, "total_buckets": 288, "ok_percent": 100.0},
        "preflight": {"passed": True}, "month_fetch_errors": [],
        "buckets": [{"month": m, "hour": h, "status": "ok",
                     "hourly_sample_count": 30, "distinct_day_count": 30,
                     "distinct_year_count": 3, "years_present": [2021, 2023, 2025],
                     "mean": -0.1, "median": 0.0, "std": 1.0, "mad": .5,
                     "p05": -2.0, "p25": -1.0, "p75": 1.0, "p95": 2.0}
                    for m in range(1, 13) for h in range(24)],
    }
    profile_path = profiles / "profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    catalog = root / "station_baseline_catalog_final_long.csv"
    with catalog.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "station_id", "station_name", "pollutant", "status", "channels", "unit", "reason"))
        writer.writeheader()
        for pollutant in ("NO2", "O3", "PM10", "PM2.5", "SO2"):
            writer.writerow({"station_id": 1, "station_name": "Station", "pollutant": pollutant,
                             "status": "FULL_BASELINE" if pollutant == "NO2" else "NOT_MEASURED",
                             "channels": "4" if pollutant == "NO2" else "",
                             "unit": "µg/m³" if pollutant == "NO2" else "", "reason": ""})
    return root, profile_path, profile


def test_import_plan_is_exact_read_only_and_keeps_unknown_generation_time(tmp_path):
    root, profile_path, profile = artifacts(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    plan = build_import_plan(root, expected_profiles=1, expected_stations=1)
    assert plan["row_counts"] == {"station_catalog": 1, "baseline_profiles": 1,
                                  "baseline_versions": 1, "baseline_buckets": 288}
    assert plan["dry_run"] is True and plan["imported_at"] is None
    assert plan["versions"][0]["generated_at"] is None
    assert plan["versions"][0]["method_version"] is None
    assert plan["versions"][0]["source_version"] is None
    assert plan["versions"][0]["aggregation_policy_version"] == HISTORICAL_AGGREGATION_POLICY
    assert plan["versions"][0]["quality_policy_version"] == HISTORICAL_QUALITY_POLICY
    assert plan["versions"][0]["lifecycle_status"] == "draft"
    assert plan["versions"][0]["quality_metadata"]["rules"]["signed_values_preserved"] is True
    assert plan["station_catalog"][0]["availability"][0]["channel_ids"] == ["4"]
    assert plan["profiles"][0] == {"provider": MINISTRY_PROVIDER_ID, "station_id": "1",
                                    "channel_id": "4", "pollutant": "NO2",
                                    "canonical_unit": "µg/m³",
                                    "baseline_family": "completed_hour"}
    assert HISTORICAL_BASELINE_FAMILY == "completed_hour"
    assert plan["buckets"][0]["mean"] == profile["buckets"][0]["mean"] == -.1
    assert plan["profile_checksums"][0]["content_sha256"] == hashlib.sha256(profile_path.read_bytes()).hexdigest()
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_malformed_profile_refuses_entire_plan(tmp_path):
    root, profile_path, _ = artifacts(tmp_path)
    profile_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="validation failed"):
        build_import_plan(root, expected_profiles=1, expected_stations=1)


def test_dry_run_cli_database_import_is_lexically_guarded():
    source = open("scripts/import_air_pollution_baselines.py", encoding="utf-8").read()
    before_guard, after_guard = source.split("if args.write:", maxsplit=1)
    assert "ecoguard.database" not in before_guard
    assert "from ecoguard.database.repositories.air_pollution_baselines" in after_guard
    assert "--confirm-write" in source


def test_dry_run_cli_emits_json_only_on_stdout(monkeypatch, capsys):
    import scripts.import_air_pollution_baselines as cli
    monkeypatch.setattr(cli, "build_import_plan", lambda _source: {
        "row_counts": {}, "profile_status_counts": {}, "bucket_counts": {},
        "catalog_content_sha256": "a" * 64, "imported_at_policy": "future transaction",
        "versions": [], "profile_checksums": [],
    })
    assert cli.main(["--summary"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["mode"] == "DRY_RUN"
    assert captured.err == ""


def test_write_mode_progress_is_stderr_and_stdout_remains_json(monkeypatch, capsys):
    import scripts.import_air_pollution_baselines as cli
    from ecoguard.database.repositories import air_pollution_baselines as repository
    monkeypatch.setattr(cli, "build_import_plan", lambda _source: {
        "row_counts": {}, "profile_status_counts": {}, "bucket_counts": {},
        "catalog_content_sha256": "a" * 64, "imported_at_policy": "future transaction",
        "versions": [], "profile_checksums": [],
    })
    def fake_import(_plan, *, progress):
        for stage in ("station catalog", "profiles", "versions", "buckets 0 / 0", "commit complete"):
            progress(stage)
        return {}
    monkeypatch.setattr(repository, "import_baseline_plan", fake_import)
    assert cli.main(["--write", "--confirm-write", "--summary"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["database_imported"] is True
    assert captured.err.splitlines() == [
        "station catalog", "profiles", "versions", "buckets 0 / 0", "commit complete",
    ]
