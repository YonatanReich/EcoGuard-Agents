"""Pure, bounded-memory builder for five-minute Air Pollution baselines."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from services.air_quality_schemas import MINISTRY_PROVIDER_ID
from services.ministry_air_quality_client import _canonical_unit

SCHEMA_VERSION = "air-pollution-five-minute-observation-baseline-v1"
CACHE_SCHEMA_VERSION = "ecoguard-air-pollution-five-minute-cache-v1"
BASELINE_FAMILY = "five_minute_observation"
METHOD_VERSION = "pooled-provider-five-minute-month-hour-v1"
QUALITY_POLICY_VERSION = "ministry-envista-five-minute-provider-valid-signed-reading-unit-v1"
AGGREGATION_POLICY_VERSION = "ministry-envista-five-minute-no-average-last-accepted-v1"
SOURCE_NAME = "Israel Ministry of Environmental Protection / Envista"
SENTINEL = -9999.0
EXPECTED_OFFSET = timedelta(hours=2)
STAT_FIELDS = ("mean", "median", "std", "mad", "p05", "p25", "p75", "p95")


class FiveMinuteBaselineError(ValueError):
    """A cache artifact cannot safely contribute to a baseline."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FiveMinuteBaselineError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def percentile(values: list[float], fraction: float) -> float:
    """Linear interpolation at ``(n-1)q``, matching national-v2."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _r4(value: float) -> float:
    return round(float(value), 4)


def _input_digest(month_files: list[dict[str, Any]]) -> str:
    stable = [
        {key: row[key] for key in ("year", "month", "cache_file", "content_sha256", "point_count")}
        for row in sorted(month_files, key=lambda row: (row["year"], row["month"]))
    ]
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _load_cache(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(gzip.decompress(raw), object_pairs_hook=_strict_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FiveMinuteBaselineError(f"unreadable cache artifact: {path.name}") from exc
    if not isinstance(payload, dict):
        raise FiveMinuteBaselineError("cache payload must be an object")
    return payload, digest


def discover_cache_profiles(cache_dir: str | Path) -> list[list[Path]]:
    """Return profile month files grouped by cache identity directory."""
    root = Path(cache_dir)
    groups: list[list[Path]] = []
    for channel_dir in sorted(root.glob("station_*/channel_*")):
        files = sorted(channel_dir.glob("????-??.json.gz"))
        if files:
            groups.append(files)
    return groups


def _cache_header(payload: dict[str, Any]) -> tuple[str, str, str, str, str, int, int]:
    semantics = payload.get("request_semantics")
    expected_semantics = {
        "resolution": "provider five-minute averages",
        "timeBeginning": False,
        "quality_filter_applied": False,
        "unit_filter_applied": False,
        "off_grid_filter_applied": False,
    }
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION or payload.get("complete") is not True:
        raise FiveMinuteBaselineError("cache schema/completion mismatch")
    if semantics != expected_semantics:
        raise FiveMinuteBaselineError("cache request semantics mismatch")
    source = payload.get("source")
    station_id = payload.get("station_id")
    station_name = payload.get("station_name")
    channel_id = payload.get("channel_id")
    pollutant = payload.get("pollutant")
    year, month = payload.get("year"), payload.get("month")
    if source != SOURCE_NAME:
        raise FiveMinuteBaselineError("unexpected historical source")
    if not all(isinstance(value, str) and value.strip() for value in (station_id, station_name, channel_id, pollutant)):
        raise FiveMinuteBaselineError("missing cache identity")
    if type(year) is not int or type(month) is not int or not 2021 <= year <= 2025 or not 1 <= month <= 12:
        raise FiveMinuteBaselineError("invalid cache year/month")
    points = payload.get("points")
    if not isinstance(points, list) or payload.get("point_count") != len(points):
        raise FiveMinuteBaselineError("cache point_count mismatch")
    return source, station_id, station_name, channel_id, pollutant, year, month


def _statistics(values: list[float]) -> dict[str, float]:
    center = statistics.median(values)
    return {
        "mean": _r4(statistics.fmean(values)),
        "median": _r4(center),
        "std": _r4(statistics.stdev(values) if len(values) > 1 else 0.0),
        "mad": _r4(statistics.median(abs(value - center) for value in values)),
        "p05": _r4(percentile(values, 0.05)),
        "p25": _r4(percentile(values, 0.25)),
        "p75": _r4(percentile(values, 0.75)),
        "p95": _r4(percentile(values, 0.95)),
    }


def build_profile(
    cache_files: Iterable[str | Path],
    *,
    expected_months: int = 60,
    minimum_years: int = 3,
    minimum_days: int = 30,
    minimum_samples: int = 270,
) -> dict[str, Any]:
    """Build one compact profile while retaining at most one identity in memory."""
    paths = sorted(Path(item) for item in cache_files)
    if len(paths) != expected_months:
        raise FiveMinuteBaselineError(f"expected {expected_months} cache months; found {len(paths)}")
    identity: tuple[str, str, str, str, str] | None = None
    provider_units: set[str] = set()
    canonical_units: set[str] = set()
    station_name: str | None = None
    month_keys: set[tuple[int, int]] = set()
    month_files: list[dict[str, Any]] = []
    grouped: dict[tuple[int, int], list[tuple[str, float, str, int]]] = defaultdict(list)
    audit: Counter[str] = Counter()

    for path in paths:
        payload, digest = _load_cache(path)
        source, sid, name, cid, pollutant, year, month = _cache_header(payload)
        current = (source, sid, cid, pollutant, name)
        if identity is None:
            identity, station_name = current, name
        elif current != identity:
            raise FiveMinuteBaselineError("cache files mix profile identities")
        if (year, month) in month_keys:
            raise FiveMinuteBaselineError("duplicate cache month-target")
        month_keys.add((year, month))
        month_files.append({
            "year": year,
            "month": month,
            "cache_file": path.name,
            "content_sha256": digest,
            "point_count": payload["point_count"],
        })

        accepted_by_timestamp: dict[str, tuple[float, str, int]] = {}
        for point in payload["points"]:
            audit["raw_points"] += 1
            if not isinstance(point, dict) or not isinstance(point.get("channels"), list):
                audit["malformed_points"] += 1
                continue
            timestamp = point.get("datetime")
            try:
                parsed = datetime.fromisoformat(str(timestamp))
            except (TypeError, ValueError):
                audit["malformed_timestamps"] += 1
                continue
            if parsed.tzinfo is None or parsed.utcoffset() != EXPECTED_OFFSET:
                audit["wrong_provider_offset"] += 1
                continue
            if parsed.year != year or parsed.month != month:
                audit["timestamp_month_mismatch"] += 1
                continue
            if parsed.minute % 5 or parsed.second or parsed.microsecond:
                audit["off_grid_timestamps"] += 1
                continue

            matches = [
                channel for channel in point["channels"]
                if isinstance(channel, dict)
                and str(channel.get("id")) == cid
                and str(channel.get("name", "")).upper().replace("PM25", "PM2.5") == pollutant.upper()
            ]
            if len(matches) != 1:
                audit["identity_mismatch"] += 1
                continue
            channel = matches[0]
            if channel.get("valid") is not True:
                audit["provider_invalid"] += 1
                continue
            value = channel.get("value")
            if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value):
                audit["missing_malformed_or_nonfinite"] += 1
                continue
            if float(value) == SENTINEL:
                audit["sentinel"] += 1
                continue
            reading_unit = channel.get("units")
            if not isinstance(reading_unit, str) or not reading_unit.strip():
                audit["reading_unit_missing"] += 1
                continue
            canonical = _canonical_unit(reading_unit)
            if canonical is None:
                audit["reading_unit_missing"] += 1
                continue
            provider_units.add(reading_unit.strip())
            canonical_units.add(canonical)
            key = str(timestamp)
            if key in accepted_by_timestamp:
                audit["duplicate_timestamp_revisions"] += 1
            accepted_by_timestamp[key] = (float(value), parsed.date().isoformat(), parsed.hour)

        audit["accepted_unique_observations"] += len(accepted_by_timestamp)
        for timestamp, (value, day, hour) in accepted_by_timestamp.items():
            grouped[(month, hour)].append((timestamp, value, day, year))

    if identity is None or station_name is None:
        raise FiveMinuteBaselineError("empty cache profile")
    if len(canonical_units) != 1:
        raise FiveMinuteBaselineError(f"reading-unit conflict or absence: {sorted(canonical_units)}")
    canonical_unit = next(iter(canonical_units))

    buckets: list[dict[str, Any]] = []
    usable = 0
    for month in range(1, 13):
        for hour in range(24):
            samples = sorted(grouped.get((month, hour), []), key=lambda item: item[0])
            values = [item[1] for item in samples]
            days = {item[2] for item in samples}
            years = sorted({item[3] for item in samples})
            sufficient = (
                len(values) >= minimum_samples
                and len(days) >= minimum_days
                and len(years) >= minimum_years
            )
            usable += int(sufficient)
            bucket: dict[str, Any] = {
                "month": month,
                "hour": hour,
                "status": "ok" if sufficient else "insufficient_history",
                "sample_count": len(values),
                "distinct_days": len(days),
                "distinct_years": len(years),
                "years_present": years,
            }
            if values:
                bucket.update(_statistics(values))
            else:
                bucket.update({field: None for field in STAT_FIELDS})
            buckets.append(bucket)

    coverage_status = (
        "FULL_BASELINE" if usable == 288
        else "PARTIAL_BASELINE" if usable
        else "INSUFFICIENT_HISTORY"
    )
    _source, sid, cid, pollutant, _name = identity
    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_family": BASELINE_FAMILY,
        "method_version": METHOD_VERSION,
        "source": {"provider": MINISTRY_PROVIDER_ID, "name": SOURCE_NAME, "cache_schema": CACHE_SCHEMA_VERSION},
        "identity": {
            "provider": MINISTRY_PROVIDER_ID,
            "station_id": sid,
            "station_name": station_name,
            "channel_id": cid,
            "pollutant": pollutant,
            "canonical_unit": canonical_unit,
        },
        "historical_units_observed": sorted(provider_units),
        "training_period": {"start": "2021-01-01", "end": "2025-12-31"},
        "generated_at": None,
        "time_semantics": {
            "provider_offset": "+02:00",
            "timeBeginning": False,
            "bucket_rule": "provider_returned_month_and_hour; no DST conversion",
        },
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "quality_policy": {
            "provider_valid_required": True,
            "finite_required": True,
            "sentinel_values_rejected": [-9999],
            "reading_unit_required": True,
            "signed_values_preserved": True,
        },
        "aggregation_policy_version": AGGREGATION_POLICY_VERSION,
        "aggregation": {
            "source_resolution_minutes": 5,
            "group_by": ["month", "hour"],
            "hourly_mean": False,
            "exact_timestamp_duplicates": "last_accepted",
            "quantiles": "linear_(n-1)*q",
            "standard_deviation": "sample_ddof_1",
            "spread": "unscaled_median_absolute_deviation",
        },
        "coverage_status": coverage_status,
        "coverage_policy": {
            "minimum_distinct_years": minimum_years,
            "minimum_distinct_days": minimum_days,
            "minimum_samples": minimum_samples,
        },
        "coverage_summary": {
            "usable_buckets": usable,
            "insufficient_buckets": 288 - usable,
            "total_buckets": 288,
        },
        "quality_summary": dict(sorted(audit.items())),
        "input_cache": {
            "profile_input_sha256": _input_digest(month_files),
            "month_file_count": len(month_files),
            "month_files": sorted(month_files, key=lambda row: (row["year"], row["month"])),
        },
        "buckets": buckets,
        "limitations": [
            "Descriptive five-minute distributions are not health or severity thresholds.",
            "Provider-valid readings are preliminary provider evidence, not scientific validation.",
            "Serially correlated observations and uneven monitor uptime remain limitations.",
            "Historical last-accepted duplicates differ from live first-seen persistence.",
        ],
    }
