"""Pure dry-run adapter for validated five-minute baseline artifacts."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from ecoguard.detectors.air_pollution.baseline_import import build_import_plan as build_completed_hour_plan
from ecoguard.detectors.air_pollution.five_minute_baseline import BASELINE_FAMILY, CACHE_SCHEMA_VERSION
from ecoguard.detectors.air_pollution.five_minute_baseline_validation import validate_artifacts


def build_import_plan(
    source_dir: str | Path,
    *,
    cache_dir: str | Path,
    completed_hour_source: str | Path,
    expected_profiles: int = 388,
    expected_stations: int = 276,
) -> dict[str, Any]:
    """Build database-shaped rows without importing SQLAlchemy or connecting."""
    root = Path(source_dir)
    validation = validate_artifacts(
        root / "profiles", cache_dir=cache_dir, expected_profiles=expected_profiles
    )
    if validation["errors"] or validation["validation"] != "PASS":
        raise ValueError("five-minute artifact validation failed: " + "; ".join(validation["errors"][:10]))

    # Reuse the exact already-imported station catalog proposal. Supplying the
    # same rows makes persistence idempotent and avoids inventing a second catalog.
    completed = build_completed_hour_plan(
        completed_hour_source,
        expected_profiles=expected_profiles,
        expected_stations=expected_stations,
    )
    profile_rows: list[dict[str, Any]] = []
    version_rows: list[dict[str, Any]] = []
    bucket_rows: list[dict[str, Any]] = []
    checksums: list[dict[str, Any]] = []
    for candidate in validation["profiles"]:
        payload = candidate["profile"]
        source_identity = payload["identity"]
        identity = {
            field: source_identity[field]
            for field in ("provider", "station_id", "channel_id", "pollutant", "canonical_unit")
        }
        identity["baseline_family"] = BASELINE_FAMILY
        profile_rows.append(identity)
        digest = candidate["content_sha256"]
        version_key = {"profile_identity": identity, "content_sha256": digest}
        version_rows.append({
            **version_key,
            "parent_content_sha256": None,
            "schema_version": payload["schema_version"],
            "method_version": payload["method_version"],
            "source_name": payload["source"]["name"],
            "source_version": CACHE_SCHEMA_VERSION,
            "training_start": date.fromisoformat(payload["training_period"]["start"]),
            "training_end": date.fromisoformat(payload["training_period"]["end"]),
            "generated_at": None,
            "aggregation_policy_version": payload["aggregation_policy_version"],
            "quality_policy_version": payload["quality_policy_version"],
            "coverage_status": payload["coverage_status"],
            "lifecycle_status": "draft",
            "source_metadata": {
                "station_name": source_identity["station_name"],
                "historical_units_observed": payload["historical_units_observed"],
                "cache_schema": payload["source"]["cache_schema"],
                "profile_input_sha256": payload["input_cache"]["profile_input_sha256"],
                "month_file_count": payload["input_cache"]["month_file_count"],
                "month_files": payload["input_cache"]["month_files"],
            },
            "aggregation_metadata": {
                "time_semantics": payload["time_semantics"],
                "aggregation": payload["aggregation"],
            },
            "quality_metadata": {
                "policy": payload["quality_policy"],
                "summary": payload["quality_summary"],
                "limitations": payload["limitations"],
            },
            "coverage_metadata": {
                "policy": payload["coverage_policy"],
                "summary": payload["coverage_summary"],
            },
        })
        for bucket in payload["buckets"]:
            bucket_rows.append({
                **version_key,
                **{field: bucket[field] for field in (
                    "month", "hour", "status", "sample_count", "distinct_days",
                    "distinct_years", "years_present", "mean", "median", "std",
                    "mad", "p05", "p25", "p75", "p95",
                )},
            })
        checksums.append({
            "identity": list(candidate["identity"]),
            "content_sha256": digest,
            "profile_input_sha256": payload["input_cache"]["profile_input_sha256"],
        })

    counts = {
        "station_catalog": len(completed["station_catalog"]),
        "baseline_profiles": len(profile_rows),
        "baseline_versions": len(version_rows),
        "baseline_buckets": len(bucket_rows),
    }
    return {
        "plan_schema": "air-pollution-baseline-import-plan-v1",
        "dry_run": True,
        "imported_at": None,
        "imported_at_policy": "Assign actual UTC transaction time only during an explicitly approved import.",
        "row_counts": counts,
        "profile_status_counts": validation["status_counts"],
        "bucket_counts": validation["bucket_counts"],
        "catalog_content_sha256": completed["catalog_content_sha256"],
        "profile_checksums": checksums,
        "station_catalog": completed["station_catalog"],
        "profiles": profile_rows,
        "versions": version_rows,
        "buckets": bucket_rows,
    }
