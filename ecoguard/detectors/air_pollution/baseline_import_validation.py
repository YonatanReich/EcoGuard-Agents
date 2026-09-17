"""Offline national-v2 contract audit. No DB, network, environment or file writes.

Statistics are validated, never recomputed or corrected. Checksums cover original
file bytes. Manifest versions are staging candidates, not detector-ready versions.
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = "air-pollution-national-baseline-v2"
POLLUTANTS = {"NO2", "O3", "PM10", "PM2.5", "SO2"}
STATS = ("mean", "median", "std", "mad", "p05", "p25", "p75", "p95")
BUCKETS = {(m, h) for m in range(1, 13) for h in range(24)}
TIME_RULE = "Use provider timestamps as returned; no Asia/Jerusalem DST conversion."
BLOCKERS = []  # Compatibility decisions approved; persistence/activation remain out of scope.


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _int(value, minimum=0):
    return type(value) is int and value >= minimum


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_profile(p):
    """Return all detectable contract errors without mutating the source object."""
    errors = []
    def check(ok, message):
        if not ok:
            errors.append(message)
    if not isinstance(p, dict):
        return ["profile must be an object"]
    station = p.get("station", {})
    if not isinstance(station, dict):
        station = {}
    check(_int(station.get("id"), 1), "station_id")
    check(isinstance(station.get("name"), str) and bool(station["name"].strip()), "station_name")
    check(_int(p.get("channel_id"), 1), "channel_id")
    check(p.get("pollutant") in POLLUTANTS, "unexpected pollutant")
    check(p.get("historical_unit") in {"µg/m³", "mg/m³", "ng/m³", "ppb", "ppm"}, "historical_unit")
    check(p.get("historical_units_observed") == [p.get("historical_unit")], "unit conflict")
    check(p.get("schema_version") == SCHEMA, "schema_version")
    check(p.get("source") == "Israel Ministry of Environmental Protection / Envista", "source")
    check(p.get("training_period") == {"start_year": 2021, "end_year": 2025}, "training_range")
    check(p.get("time_semantics") == {"rule": TIME_RULE}, "time_semantics")
    check(p.get("hourly_aggregation") == {
        "source_resolution_minutes": 5, "min_valid_points_per_hour": 9,
        "method": "arithmetic_mean_of_valid_unique_measurements",
    }, "hourly_aggregation")
    check(p.get("coverage_policy") == {
        "min_distinct_years_per_bucket": 3, "min_distinct_days_per_bucket": 30,
    }, "coverage_policy")
    rows = p.get("buckets")
    if not isinstance(rows, list):
        return errors + ["buckets must be a list"]
    seen = set()
    usable = total_samples = 0
    for index, b in enumerate(rows):
        prefix = f"bucket[{index}]"
        if not isinstance(b, dict):
            errors.append(prefix + " must be an object")
            continue
        month, hour = b.get("month"), b.get("hour")
        if not (_int(month, 1) and month <= 12 and _int(hour) and hour < 24):
            errors.append(prefix + " invalid month/hour")
            continue
        key = (month, hour)
        check(key not in seen, prefix + " duplicate month/hour")
        seen.add(key)
        n, days, years = (b.get(k) for k in (
            "hourly_sample_count", "distinct_day_count", "distinct_year_count"))
        if not all(_int(v) for v in (n, days, years)):
            errors.append(prefix + " invalid counts")
            continue
        total_samples += n
        check(n == days and years <= days, prefix + " count consistency")
        ys = b.get("years_present")
        years_ok = isinstance(ys, list) and all(_int(y) and 2021 <= y <= 2025 for y in ys)
        check(years_ok and ys == sorted(set(ys)) and len(ys) == years, prefix + " years_present")
        if years_ok:
            check(n <= sum(calendar.monthrange(y, month)[1] for y in ys), prefix + " exceeds calendar capacity")
        enough = years >= 3 and days >= 30
        check(b.get("status") == ("ok" if enough else "insufficient_history"), prefix + " status/coverage")
        usable += enough
        for stat in STATS:
            check(_number(b.get(stat)) if n else b.get(stat) is None, prefix + " " + stat)
        if n and all(_number(b.get(s)) for s in STATS):
            check(b["std"] >= 0 and b["mad"] >= 0, prefix + " negative spread")
            check(b["p05"] <= b["p25"] <= b["median"] <= b["p75"] <= b["p95"], prefix + " quantile ordering")
            if n == 1:
                check(b["std"] == b["mad"] == 0, prefix + " singleton spread")
    check(seen == BUCKETS and len(rows) == 288, f"bucket structure: missing={len(BUCKETS-seen)} rows={len(rows)}")
    status = "ok" if usable == 288 else "partial_coverage" if usable else "insufficient_history"
    check(p.get("profile_status") == status, "profile status/coverage")
    check(p.get("coverage_summary") == {"ok_buckets": usable, "total_buckets": 288,
          "ok_percent": round(usable / 288 * 100, 2)}, "coverage_summary")
    quality = p.get("quality_summary")
    check(isinstance(quality, dict) and quality.get("accepted_hourly_values") == total_samples, "quality hourly total")
    return errors


def build_manifest(profiles_dir, catalog_path, *, expected_profiles=388, expected_stations=276):
    """Read local artifacts; return a reproducible manifest in memory only."""
    errors, versions, negatives = [], [], []
    identities, channels, stations = set(), defaultdict(set), {}
    status_counts = Counter()
    bucket_counts = Counter()
    warnings = set()
    paths = sorted(Path(profiles_dir).glob("*.json"))
    if len(paths) != expected_profiles:
        errors.append(f"expected {expected_profiles} profile files; found {len(paths)}")
    for path in paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        try:
            p = json.loads(raw, object_pairs_hook=_pairs)
            issues = validate_profile(p)
        except (ValueError, TypeError, KeyError, OverflowError):
            p, issues = {}, ["malformed JSON/profile structure"]
        label = path.name  # diagnostic label, not scientific provenance
        errors.extend(f"{label}: {issue}" for issue in issues)
        if issues:
            versions.append({"artifact": label, "content_sha256": digest, "valid": False})
            continue
        sid, name = p["station"]["id"], p["station"]["name"]
        identity = (sid, p["channel_id"], p["pollutant"], p["historical_unit"])
        if identity in identities:
            errors.append(f"duplicate identity: {identity}")
        identities.add(identity)
        channels[(sid, p["channel_id"])].add((p["pollutant"], p["historical_unit"]))
        if sid in stations and stations[sid] != name:
            errors.append(f"station name conflict: {sid}")
        stations[sid] = name
        status = {"ok": "FULL_BASELINE", "partial_coverage": "PARTIAL_BASELINE",
                  "insufficient_history": "INSUFFICIENT_HISTORY"}[p["profile_status"]]
        status_counts[status] += 1
        negative_fields = defaultdict(list)
        for b in p["buckets"]:
            bucket_counts["total"] += 1
            bucket_counts[b["status"]] += 1
            bucket_counts["empty"] += b["hourly_sample_count"] == 0
            for stat in STATS:
                if _number(b.get(stat)) and b[stat] < 0:
                    negative_fields[stat].append({"month": b["month"], "hour": b["hour"], "value": b[stat]})
        if negative_fields:
            negatives.append({"identity": identity, "station_name": name, "fields": dict(negative_fields)})
        if p.get("metadata_unit") != p["historical_unit"]:
            warnings.add("Station metadata units differ from actual historical units; never substitute them.")
        if not p.get("generated_at"):
            warnings.add("Historical generated_at is unknown; retain null, not file mtime or import time.")
        if p.get("month_fetch_errors"):
            warnings.add("Some profiles record failed monthly fetches; retain coverage limitations.")
        versions.append({
            "artifact": label, "identity": identity, "station_name": name, "status": status,
            "content_sha256": digest, "valid": True, "lifecycle": "staging_only",
            "generated_at": p.get("generated_at"), "imported_at": None,
            "source": p["source"], "schema_version": p["schema_version"],
            "method_version": None, "training_period": p["training_period"],
            "time_semantics": p["time_semantics"], "hourly_aggregation": p["hourly_aggregation"],
            "coverage_policy": p["coverage_policy"], "coverage_summary": p["coverage_summary"],
            "quality_summary": p["quality_summary"],
            "month_fetch_error_count": len(p.get("month_fetch_errors", [])),
            "bucket_rows": len(p["buckets"]),
        })
    for key, values in sorted(channels.items()):
        if len(values) != 1:
            errors.append(f"channel conflict: {key} {sorted(values)}")
    if len(identities) != expected_profiles:
        errors.append(f"expected {expected_profiles} unique identities; found {len(identities)}")
    catalog = {}
    pairs = set()
    with Path(catalog_path).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                sid = int(row["station_id"])
                pol = row["pollutant"]
                if not (sid > 0 and row["station_name"].strip() and pol in POLLUTANTS):
                    raise ValueError("invalid catalog identity")
                if row["status"] not in {"FULL_BASELINE", "PARTIAL_BASELINE", "INSUFFICIENT_HISTORY",
                                         "NOT_MEASURED", "EXCLUDED_MOBILE_OR_INACTIVE"}:
                    raise ValueError("invalid catalog status")
                if (sid, pol) in pairs:
                    errors.append(f"duplicate catalog station/pollutant: {sid}/{pol}")
                pairs.add((sid, pol))
                entry = catalog.setdefault(sid, {"station_id": sid, "station_name": row["station_name"], "availability": []})
                if entry["station_name"] != row["station_name"]:
                    errors.append(f"catalog station name conflict: {sid}")
                entry["availability"].append({k: row[k] for k in ("pollutant", "status", "channels", "unit", "reason")})
            except (KeyError, ValueError):
                errors.append("malformed catalog row")
    if len(catalog) != expected_stations or len(pairs) != expected_stations * 5:
        errors.append("catalog station/pollutant count mismatch")
    for sid, name in stations.items():
        if sid not in catalog or catalog[sid]["station_name"] != name:
            errors.append(f"profile/catalog station mismatch: {sid}")
    for v in versions:
        if not v["valid"]:
            continue
        sid, cid, pol, unit = v["identity"]
        matches = [r for r in catalog.get(sid, {}).get("availability", []) if r["pollutant"] == pol]
        if len(matches) != 1 or str(cid) not in matches[0]["channels"].split(",") or matches[0]["unit"] != unit or matches[0]["status"] != v["status"]:
            errors.append(f"profile/catalog channel, unit or status mismatch: {sid}/{cid}/{pol}")
    warnings.update([
        "Legacy observations without explicit unit/quality provenance are not comparison eligible.",
        "Live first_seen and historical last-accepted duplicate policies intentionally differ (approved).",
        "Signed provider-valid ingestion is an EcoGuard policy, not Ministry scientific validation.",
        "Summary statistics cannot establish raw min/max or verify statistics by recomputation without contributing data.",
        "No source revision, method revision, raw input checksum, or first/last contributing timestamp is recorded.",
        "Historical dedup is last-write-wins by timestamp string; live DB is first-write-wins by UTC instant.",
        "Historical builder does not enforce five-minute grid alignment and can accept readings with missing units.",
        "Catalog availability is station/pollutant-level, not an exact channel baseline or complete monitor inventory.",
    ])
    if negatives:
        warnings.add("Negative statistics preserved unchanged; no scientific acceptability cutoff inferred.")
    return {
        "manifest_schema": "air-pollution-offline-import-v1", "offline_only": True,
        "artifact_validation": "FAIL" if errors else "PASS",
        "staging_import_readiness": "FAIL" if errors else "PASS",
        "operational_import_readiness": "FAIL" if errors else "PASS", "activation_allowed": False,
        "readiness_scope": "compact baseline migration design; not detector activation",
        "compatibility_contract": {
            "quality_policy": "ecoguard-provider-valid-signed-v1",
            "aggregation_policy": "ecoguard-live-provider-hour-first-seen-v1",
            "clock": "fixed UTC+02:00; national-v2 timeBeginning=false labels",
            "units": "reading provenance required; no metadata fallback comparison",
            "evidence": "docs/air_pollution_operational_compatibility.md",
        },
        "errors": errors, "blockers": BLOCKERS, "warnings": sorted(warnings),
        "row_counts": {"station_catalog": len(catalog), "baseline_profiles": len(identities),
                       "baseline_versions": sum(v["valid"] for v in versions), "baseline_buckets": bucket_counts["total"]},
        "profile_status_counts": dict(status_counts), "bucket_counts": dict(bucket_counts),
        "missing_structural_buckets": expected_profiles * 288 - bucket_counts["total"],
        "stations_with_profiles": len(stations),
        "catalog_content_sha256": hashlib.sha256(Path(catalog_path).read_bytes()).hexdigest(),
        "imported_at_policy": "Assign actual UTC transaction time only at a future approved import.",
        "station_catalog": [catalog[k] for k in sorted(catalog)], "versions": versions,
        "negative_profiles": negatives,
    }
