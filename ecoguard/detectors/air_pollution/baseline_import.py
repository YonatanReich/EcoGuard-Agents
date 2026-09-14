"""Pure adapter from validated national-v2 artifacts to proposed database rows.

This module has no SQLAlchemy, environment, database or network dependency. It
reads but never writes source artifacts and refuses the whole plan on any error.
"""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from ecoguard.detectors.air_pollution.baseline_import_validation import build_manifest
from ecoguard.shared.air_quality_schemas import MINISTRY_PROVIDER_ID

HISTORICAL_AGGREGATION_POLICY = "ministry-envista-national-v2-timebeginning-false-hourly-v1"
HISTORICAL_QUALITY_POLICY = "ministry-envista-national-v2-provider-valid-signed-v1"
HISTORICAL_BASELINE_FAMILY = "completed_hour"


def _generated_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("generated_at must be an ISO timestamp or null")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("generated_at must carry a UTC offset")
    return parsed


def build_import_plan(source_dir: str | Path, *, expected_profiles=388, expected_stations=276) -> dict[str, Any]:
    """Return database-shaped rows in memory, with source bytes checksummed twice."""
    root = Path(source_dir)
    profiles_dir = root / "profiles"
    catalog_path = root / "station_baseline_catalog_final_long.csv"
    manifest = build_manifest(
        profiles_dir, catalog_path,
        expected_profiles=expected_profiles, expected_stations=expected_stations,
    )
    if manifest["errors"] or manifest["artifact_validation"] != "PASS":
        raise ValueError("baseline artifact validation failed: " + "; ".join(manifest["errors"][:10]))

    catalog_rows = [{
        "provider": MINISTRY_PROVIDER_ID,
        "station_id": str(row["station_id"]),
        "station_name": row["station_name"],
        "availability": [{
            "pollutant": item["pollutant"],
            "status": item["status"],
            "channel_ids": [part for part in item["channels"].split(",") if part],
            "canonical_unit": item["unit"] or None,
            "reason": item["reason"] or None,
        } for item in row["availability"]],
        "artifact_sha256": manifest["catalog_content_sha256"],
    } for row in manifest["station_catalog"]]

    profile_rows, version_rows, bucket_rows = [], [], []
    for candidate in manifest["versions"]:
        path = profiles_dir / candidate["artifact"]
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != candidate["content_sha256"]:
            raise ValueError(f"profile changed during validation: {candidate['artifact']}")
        payload = json.loads(raw)
        sid, channel, pollutant, unit = candidate["identity"]
        identity = {
            "provider": MINISTRY_PROVIDER_ID,
            "station_id": str(sid),
            "channel_id": str(channel),
            "pollutant": pollutant,
            "canonical_unit": unit,
            # national-v2 contains completed-hour statistics. This assignment
            # is fixed by the adapter and deliberately is not a CLI choice.
            "baseline_family": HISTORICAL_BASELINE_FAMILY,
        }
        profile_rows.append(identity)
        period = payload["training_period"]
        version_key = {"profile_identity": identity, "content_sha256": digest}
        version_rows.append({
            **version_key,
            "parent_content_sha256": None,
            "schema_version": payload["schema_version"],
            # These revisions are absent from national-v2; null is auditable.
            "method_version": None,
            "source_name": payload["source"],
            "source_version": None,
            "training_start": date(period["start_year"], 1, 1),
            "training_end": date(period["end_year"], 12, 31),
            "generated_at": _generated_at(payload.get("generated_at")),
            "aggregation_policy_version": HISTORICAL_AGGREGATION_POLICY,
            "quality_policy_version": HISTORICAL_QUALITY_POLICY,
            "coverage_status": candidate["status"],
            "lifecycle_status": "draft",
            "source_metadata": {
                "metadata_unit": payload.get("metadata_unit"),
                "historical_units_observed": payload["historical_units_observed"],
                "monitor_active_metadata": payload.get("monitor_active_metadata"),
                "preflight": payload.get("preflight"),
                "month_fetch_errors": payload.get("month_fetch_errors", []),
            },
            "aggregation_metadata": {
                "time_semantics": payload["time_semantics"],
                "hourly_aggregation": payload["hourly_aggregation"],
            },
            "quality_metadata": {
                "quality_summary": payload["quality_summary"],
                "rules": {
                    "provider_valid_required": True,
                    "finite_required": True,
                    "missing_rejected": True,
                    "sentinel_values_rejected": [-9999],
                    "signed_values_preserved": True,
                    "independent_status_filter": False,
                },
            },
            "coverage_metadata": {
                "coverage_policy": payload["coverage_policy"],
                "coverage_summary": payload["coverage_summary"],
            },
        })
        for bucket in payload["buckets"]:
            bucket_rows.append({
                **version_key,
                "month": bucket["month"], "hour": bucket["hour"],
                "status": bucket["status"],
                "sample_count": bucket["hourly_sample_count"],
                "distinct_days": bucket["distinct_day_count"],
                "distinct_years": bucket["distinct_year_count"],
                "years_present": bucket["years_present"],
                **{field: bucket.get(field) for field in
                   ("mean", "median", "std", "mad", "p05", "p25", "p75", "p95")},
            })

    counts = {
        "station_catalog": len(catalog_rows),
        "baseline_profiles": len(profile_rows),
        "baseline_versions": len(version_rows),
        "baseline_buckets": len(bucket_rows),
    }
    if counts != manifest["row_counts"]:
        raise ValueError(f"import plan counts disagree with validation: {counts}")
    return {
        "plan_schema": "air-pollution-baseline-import-plan-v1",
        "dry_run": True,
        "imported_at": None,
        "imported_at_policy": manifest["imported_at_policy"],
        "row_counts": counts,
        "profile_status_counts": manifest["profile_status_counts"],
        "bucket_counts": manifest["bucket_counts"],
        "catalog_content_sha256": manifest["catalog_content_sha256"],
        "profile_checksums": [
            {"identity": list(row["identity"]), "content_sha256": row["content_sha256"]}
            for row in manifest["versions"]
        ],
        "station_catalog": catalog_rows,
        "profiles": profile_rows,
        "versions": version_rows,
        "buckets": bucket_rows,
    }
