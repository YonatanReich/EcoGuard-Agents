"""Offline validation for five-minute baseline artifacts and cache hashes."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from ecoguard.detectors.air_pollution.five_minute_baseline import (
    AGGREGATION_POLICY_VERSION,
    BASELINE_FAMILY,
    CACHE_SCHEMA_VERSION,
    METHOD_VERSION,
    QUALITY_POLICY_VERSION,
    SCHEMA_VERSION,
    STAT_FIELDS,
    _input_digest,
    _strict_object,
)
from ecoguard.shared.air_quality_schemas import MINISTRY_PROVIDER_ID

EXPECTED_BUCKETS = {(month, hour) for month in range(1, 13) for hour in range(24)}
EXPECTED_COVERAGE_POLICY = {
    "minimum_distinct_years": 3,
    "minimum_distinct_days": 30,
    "minimum_samples": 270,
}


def _integer(value: Any, minimum: int = 0) -> bool:
    """Whether this is a whole number at or above the minimum."""
    return type(value) is int and value >= minimum


def _number(value: Any) -> bool:
    """Whether this is a real, finite number."""
    return type(value) in (int, float) and math.isfinite(value)


def validate_profile(profile: Any) -> list[str]:
    """Every structural problem with a baseline profile, as a list of messages."""
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        """Record a message when the condition fails."""
        if not condition:
            errors.append(message)

    if not isinstance(profile, dict):
        return ["profile must be an object"]
    identity = profile.get("identity")
    if not isinstance(identity, dict):
        return ["identity must be an object"]
    check(profile.get("schema_version") == SCHEMA_VERSION, "schema_version")
    check(profile.get("baseline_family") == BASELINE_FAMILY, "baseline_family")
    check(profile.get("method_version") == METHOD_VERSION, "method_version")
    check(profile.get("quality_policy_version") == QUALITY_POLICY_VERSION, "quality_policy_version")
    check(profile.get("aggregation_policy_version") == AGGREGATION_POLICY_VERSION, "aggregation_policy_version")
    check(identity.get("provider") == MINISTRY_PROVIDER_ID, "provider")
    for field in ("station_id", "station_name", "channel_id", "pollutant", "canonical_unit"):
        check(isinstance(identity.get(field), str) and bool(identity[field].strip()), f"identity.{field}")
    check(profile.get("training_period") == {"start": "2021-01-01", "end": "2025-12-31"}, "training_period")
    check(profile.get("generated_at") is None, "generated_at must remain null")
    check(profile.get("coverage_policy") == EXPECTED_COVERAGE_POLICY, "coverage_policy")
    check(profile.get("time_semantics") == {
        "provider_offset": "+02:00", "timeBeginning": False,
        "bucket_rule": "provider_returned_month_and_hour; no DST conversion",
    }, "time_semantics")
    aggregation = profile.get("aggregation")
    check(isinstance(aggregation, dict) and aggregation.get("hourly_mean") is False,
          "hourly averaging must be false")
    check(isinstance(aggregation, dict) and aggregation.get("group_by") == ["month", "hour"],
          "month/hour grouping")
    check(isinstance(aggregation, dict) and aggregation.get("exact_timestamp_duplicates") == "last_accepted",
          "duplicate policy")
    units = profile.get("historical_units_observed")
    check(isinstance(units, list) and len(units) == 1 and bool(str(units[0]).strip()), "reading unit provenance")

    rows = profile.get("buckets")
    if not isinstance(rows, list):
        return errors + ["buckets must be a list"]
    seen: set[tuple[int, int]] = set()
    usable = 0
    for index, bucket in enumerate(rows):
        prefix = f"bucket[{index}]"
        if not isinstance(bucket, dict):
            errors.append(prefix + " must be an object")
            continue
        month, hour = bucket.get("month"), bucket.get("hour")
        if not (_integer(month, 1) and month <= 12 and _integer(hour) and hour <= 23):
            errors.append(prefix + " invalid month/hour")
            continue
        key = (month, hour)
        check(key not in seen, prefix + " duplicate month/hour")
        seen.add(key)
        samples = bucket.get("sample_count")
        days = bucket.get("distinct_days")
        years = bucket.get("distinct_years")
        check(all(_integer(value) for value in (samples, days, years)), prefix + " invalid counts")
        if not all(_integer(value) for value in (samples, days, years)):
            continue
        check(years <= days <= samples, prefix + " count ordering")
        years_present = bucket.get("years_present")
        years_ok = (
            isinstance(years_present, list)
            and all(_integer(year, 2021) and year <= 2025 for year in years_present)
            and years_present == sorted(set(years_present))
            and len(years_present) == years
        )
        check(years_ok, prefix + " years_present")
        enough = samples >= 270 and days >= 30 and years >= 3
        check(bucket.get("status") == ("ok" if enough else "insufficient_history"), prefix + " status/coverage")
        usable += int(enough)
        for field in STAT_FIELDS:
            check(_number(bucket.get(field)) if samples else bucket.get(field) is None, prefix + f" {field}")
        if samples and all(_number(bucket.get(field)) for field in STAT_FIELDS):
            check(bucket["std"] >= 0 and bucket["mad"] >= 0, prefix + " negative spread")
            check(
                bucket["p05"] <= bucket["p25"] <= bucket["median"] <= bucket["p75"] <= bucket["p95"],
                prefix + " quantile ordering",
            )
    check(len(rows) == 288 and seen == EXPECTED_BUCKETS, "bucket structure")
    expected_status = "FULL_BASELINE" if usable == 288 else "PARTIAL_BASELINE" if usable else "INSUFFICIENT_HISTORY"
    check(profile.get("coverage_status") == expected_status, "coverage_status")
    check(profile.get("coverage_summary") == {
        "usable_buckets": usable,
        "insufficient_buckets": 288 - usable,
        "total_buckets": 288,
    }, "coverage_summary")

    cache = profile.get("input_cache")
    if not isinstance(cache, dict):
        errors.append("input_cache")
    else:
        files = cache.get("month_files")
        check(isinstance(files, list) and len(files) == 60 and cache.get("month_file_count") == 60,
              "input cache month count")
        if isinstance(files, list):
            keys = {(row.get("year"), row.get("month")) for row in files if isinstance(row, dict)}
            check(keys == {(year, month) for year in range(2021, 2026) for month in range(1, 13)},
                  "input cache month coverage")
            check(all(isinstance(row, dict) and isinstance(row.get("content_sha256"), str)
                      and len(row["content_sha256"]) == 64 for row in files), "input cache hashes")
            if all(isinstance(row, dict) for row in files):
                check(cache.get("profile_input_sha256") == _input_digest(files), "profile input hash")
    return errors


def validate_artifacts(
    profiles_dir: str | Path,
    *,
    cache_dir: str | Path | None = None,
    expected_profiles: int = 388,
) -> dict[str, Any]:
    """Validate profile bytes and, optionally, every referenced cache digest."""
    root = Path(profiles_dir)
    cache_root = Path(cache_dir) if cache_dir is not None else None
    errors: list[str] = []
    identities: set[tuple[str, ...]] = set()
    status_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    profile_rows: list[dict[str, Any]] = []
    paths = sorted(root.glob("*.json"))
    if len(paths) != expected_profiles:
        errors.append(f"expected {expected_profiles} profiles; found {len(paths)}")
    for path in paths:
        raw = path.read_bytes()
        content_hash = hashlib.sha256(raw).hexdigest()
        try:
            profile = json.loads(raw, object_pairs_hook=_strict_object)
            issues = validate_profile(profile)
        except (ValueError, TypeError, json.JSONDecodeError):
            profile, issues = {}, ["malformed JSON/profile"]
        errors.extend(f"{path.name}: {issue}" for issue in issues)
        if issues:
            continue
        identity_data = profile["identity"]
        identity = tuple(identity_data[field] for field in (
            "provider", "station_id", "channel_id", "pollutant", "canonical_unit"
        )) + (BASELINE_FAMILY,)
        if identity in identities:
            errors.append(f"duplicate profile identity: {identity}")
        identities.add(identity)
        status_counts[profile["coverage_status"]] += 1
        for bucket in profile["buckets"]:
            bucket_counts["total"] += 1
            bucket_counts[bucket["status"]] += 1
        if cache_root is not None:
            station_slug = "station_" + identity_data["station_id"].lower()
            channel_slug = "channel_" + identity_data["channel_id"].lower() + "_" + identity_data["pollutant"].lower().replace(".", "_")
            source_dir = cache_root / station_slug / channel_slug
            for item in profile["input_cache"]["month_files"]:
                source_path = source_dir / item["cache_file"]
                if not source_path.is_file():
                    errors.append(f"{path.name}: missing cache file {source_path.name}")
                elif hashlib.sha256(source_path.read_bytes()).hexdigest() != item["content_sha256"]:
                    errors.append(f"{path.name}: cache checksum mismatch {source_path.name}")
        profile_rows.append({
            "path": path,
            "profile": profile,
            "identity": identity,
            "content_sha256": content_hash,
        })
    if len(identities) != expected_profiles:
        errors.append(f"expected {expected_profiles} identities; found {len(identities)}")
    return {
        "validation": "FAIL" if errors else "PASS",
        "errors": errors,
        "profile_count": len(profile_rows),
        "identity_count": len(identities),
        "status_counts": dict(status_counts),
        "bucket_counts": dict(bucket_counts),
        "profiles": profile_rows,
        "cache_checksums_verified": cache_root is not None and not errors,
    }
