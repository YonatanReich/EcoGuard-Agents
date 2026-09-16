"""Streaming reader for the existing Ministry five-minute history cache.

This module does not download history.  It validates and reads the immutable
month artifacts produced by ``air_pollution_five_minute_cache.py``.  One call
holds one compressed month in memory, applies the same policy used by the
operational five-minute baseline, and returns at most one month of accepted
observations.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

from ecoguard.shared.ministry_air_quality_client import _canonical_unit

CACHE_SCHEMA_VERSION = "ecoguard-air-pollution-five-minute-cache-v1"
QUALITY_POLICY_VERSION = (
    "ministry-envista-five-minute-provider-valid-signed-reading-unit-v1"
)
SOURCE_NAME = "Israel Ministry of Environmental Protection / Envista"
SENTINEL = -9999.0
EXPECTED_OFFSET = timedelta(hours=2)


class AirPollutionHistoryError(ValueError):
    """A cache artifact cannot safely contribute historical observations."""


@dataclass(frozen=True, order=True)
class AirPollutionSeriesIdentity:
    station_id: str
    channel_id: str
    pollutant: str


@dataclass(frozen=True)
class HistoricalAirPollutionObservation:
    identity: AirPollutionSeriesIdentity
    observed_at: datetime
    value: float
    unit: str
    provider_unit: str


@dataclass(frozen=True)
class HistoricalAirPollutionMonth:
    path: Path
    content_sha256: str
    identity: AirPollutionSeriesIdentity
    station_name: str
    year: int
    month: int
    point_count: int
    observations: tuple[HistoricalAirPollutionObservation, ...]
    quality_summary: dict[str, int]
    provider_units: tuple[str, ...]
    canonical_units: tuple[str, ...]


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AirPollutionHistoryError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_payload(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(gzip.decompress(raw), object_pairs_hook=_strict_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AirPollutionHistoryError(
            f"unreadable cache artifact: {path.name}"
        ) from exc
    if not isinstance(payload, dict):
        raise AirPollutionHistoryError("cache payload must be an object")
    return payload, digest


def _header(
    payload: dict[str, Any],
) -> tuple[AirPollutionSeriesIdentity, str, int, int, list[Any]]:
    expected_semantics = {
        "resolution": "provider five-minute averages",
        "timeBeginning": False,
        "quality_filter_applied": False,
        "unit_filter_applied": False,
        "off_grid_filter_applied": False,
    }
    if (
        payload.get("schema_version") != CACHE_SCHEMA_VERSION
        or payload.get("complete") is not True
    ):
        raise AirPollutionHistoryError("cache schema/completion mismatch")
    if payload.get("request_semantics") != expected_semantics:
        raise AirPollutionHistoryError("cache request semantics mismatch")
    if payload.get("source") != SOURCE_NAME:
        raise AirPollutionHistoryError("unexpected historical source")

    station_id = payload.get("station_id")
    station_name = payload.get("station_name")
    channel_id = payload.get("channel_id")
    pollutant = payload.get("pollutant")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (station_id, station_name, channel_id, pollutant)
    ):
        raise AirPollutionHistoryError("missing cache identity")
    year, month = payload.get("year"), payload.get("month")
    if (
        type(year) is not int
        or type(month) is not int
        or not 2021 <= year <= 2025
        or not 1 <= month <= 12
    ):
        raise AirPollutionHistoryError("invalid cache year/month")
    points = payload.get("points")
    if not isinstance(points, list) or payload.get("point_count") != len(points):
        raise AirPollutionHistoryError("cache point_count mismatch")
    return (
        AirPollutionSeriesIdentity(station_id, channel_id, pollutant),
        station_name,
        year,
        month,
        points,
    )


def read_history_month(path: str | Path) -> HistoricalAirPollutionMonth:
    """Read and filter exactly one cache month using the baseline policy."""

    cache_path = Path(path)
    payload, digest = _load_payload(cache_path)
    identity, station_name, year, month, points = _header(payload)
    audit: Counter[str] = Counter()
    provider_units: set[str] = set()
    canonical_units: set[str] = set()
    accepted: dict[str, HistoricalAirPollutionObservation] = {}

    for point in points:
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
            channel
            for channel in point["channels"]
            if isinstance(channel, dict)
            and str(channel.get("id")) == identity.channel_id
            and str(channel.get("name", "")).upper().replace("PM25", "PM2.5")
            == identity.pollutant.upper()
        ]
        if len(matches) != 1:
            audit["identity_mismatch"] += 1
            continue
        channel = matches[0]
        if channel.get("valid") is not True:
            audit["provider_invalid"] += 1
            continue
        value = channel.get("value")
        if (
            isinstance(value, bool)
            or type(value) not in (int, float)
            or not math.isfinite(value)
        ):
            audit["missing_malformed_or_nonfinite"] += 1
            continue
        if float(value) == SENTINEL:
            audit["sentinel"] += 1
            continue
        reading_unit = channel.get("units")
        if not isinstance(reading_unit, str) or not reading_unit.strip():
            audit["reading_unit_missing"] += 1
            continue
        canonical_unit = _canonical_unit(reading_unit)
        if canonical_unit is None:
            audit["reading_unit_missing"] += 1
            continue

        provider_unit = reading_unit.strip()
        provider_units.add(provider_unit)
        canonical_units.add(canonical_unit)
        key = str(timestamp)
        if key in accepted:
            audit["duplicate_timestamp_revisions"] += 1
        accepted[key] = HistoricalAirPollutionObservation(
            identity=identity,
            observed_at=parsed,
            value=float(value),
            unit=canonical_unit,
            provider_unit=provider_unit,
        )

    audit["accepted_unique_observations"] += len(accepted)
    observations = tuple(sorted(accepted.values(), key=lambda item: item.observed_at))
    return HistoricalAirPollutionMonth(
        path=cache_path,
        content_sha256=digest,
        identity=identity,
        station_name=station_name,
        year=year,
        month=month,
        point_count=len(points),
        observations=observations,
        quality_summary=dict(sorted(audit.items())),
        provider_units=tuple(sorted(provider_units)),
        canonical_units=tuple(sorted(canonical_units)),
    )


def discover_history_series(cache_dir: str | Path) -> list[list[Path]]:
    """Return deterministic month-file groups for each canonical identity."""

    root = Path(cache_dir)
    groups: list[list[Path]] = []
    for channel_dir in sorted(root.glob("station_*/channel_*")):
        files = sorted(channel_dir.glob("????-??.json.gz"))
        if files:
            groups.append(files)
    return groups


def iter_history_months(
    cache_files: Iterable[str | Path],
) -> Iterator[HistoricalAirPollutionMonth]:
    """Yield validated months without retaining previous month payloads."""

    for path in sorted(Path(item) for item in cache_files):
        yield read_history_month(path)
