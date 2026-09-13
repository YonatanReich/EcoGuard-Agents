"""Plan and resumably acquire the isolated 300-sample archived-forecast ML pilot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import requests

from research.pilots.build_historical_forecast_risk_pilot import (
    ENDPOINT, MODEL, MODEL_AVAILABILITY_DELAY_HOURS, VARIABLES,
    ForecastPilotError, parse_utc, select_available_run, validate_forecast,
)
from ecoguard.paths import GENERATED


DATASET_PATH = GENERATED / "fire_prediction_ml_landcover_terrain_dataset_2023_2026.csv"
GRID_PATH = GENERATED / "fire_risk_grid.sqlite"
POSITIVE_CHECKPOINT = GENERATED / "historical_fire_weather_checkpoint" / "candidates"
NEGATIVE_CHECKPOINT = GENERATED / "historical_fire_negative_weather_checkpoint" / "candidates"
MANIFEST_PATH = GENERATED / "fire_forecast_risk_pilot_manifest.csv"
SNAPSHOT_PLAN_PATH = GENERATED / "fire_forecast_risk_pilot_snapshots.csv"
CACHE_PATH = GENERATED / "forecast_risk_pilot_cache" / "forecast_runs.sqlite"
HORIZONS = (12, 6, 3)
YEARS = (2024, 2025, 2026)
PER_YEAR_CLASS = 50
SELECTION_SEED = "forecast-pilot-20260828"
ARCHIVE_START = datetime(2024, 3, 14, tzinfo=timezone.utc)
SCHEMA_VERSION = 1
STANDARD_RUN_INTERVAL_HOURS = 6
MAX_RUN_FALLBACK_HOURS = 24
RUN_NOT_AVAILABLE_MESSAGE = "the requested model run is not available"


class ForecastRateLimitError(ForecastPilotError):
    pass


class ForecastRunUnavailableError(ForecastPilotError):
    """The provider has no archive for this model/run (independent of coordinate)."""

    def __init__(self, run: datetime):
        super().__init__("forecast provider model run is unavailable")
        self.run = run


def _atomic_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def load_dataset(path: Path = DATASET_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"sample_id", "sample_type", "timestamp", "latitude", "longitude", "fire_label", "label_source"}
    if not rows or not required.issubset(rows[0]):
        raise ForecastPilotError("forecast pilot input schema is incompatible")
    return rows


def _archive_utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ForecastPilotError("historical weather checkpoint timestamp is malformed") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def archive_checkpoint_coverage(directories: Iterable[Path]) -> dict[str, tuple[datetime, datetime]]:
    coverage = {}
    for directory in directories:
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
                identifier = str(payload["candidate"]["candidate_id"])
                times = [_archive_utc(value) for value in payload["weather"]["hourly"]["time"]]
                if not times:
                    raise ValueError
                coverage[identifier] = (min(times), max(times))
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                raise ForecastPilotError(f"historical weather checkpoint is corrupted: {path.name}") from None
    return coverage


def complete_for_horizons(row: Mapping[str, Any], coverage: Mapping[str, tuple[datetime, datetime]]) -> bool:
    available = coverage.get(str(row["sample_id"]))
    if not available:
        return False
    target = parse_utc(row["timestamp"])
    start, end = available
    return all(
        start <= target - timedelta(hours=horizon + 168)
        and end >= target - timedelta(hours=horizon + 1)
        for horizon in HORIZONS
    )


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088; first, second = math.radians(lat1), math.radians(lat2)
    dlat, dlon = second - first, math.radians(lon2 - lon1)
    value = math.sin(dlat / 2) ** 2 + math.cos(first) * math.cos(second) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(value)))


def grid_cells(path: Path = GRID_PATH) -> list[tuple[str, float, float]]:
    connection = sqlite3.connect(path)
    try:
        return [(str(a), float(b), float(c)) for a, b, c in connection.execute(
            "SELECT cell_id,latitude,longitude FROM risk_grid_cells WHERE active=1 ORDER BY cell_id"
        )]
    except sqlite3.Error:
        raise ForecastPilotError("risk grid is unavailable or incompatible") from None
    finally:
        connection.close()


def nearest_cell(latitude: float, longitude: float, cells: Sequence[tuple[str, float, float]]) -> str | None:
    if not cells:
        return None
    cell, distance = min(((item, _haversine(latitude, longitude, item[1], item[2])) for item in cells), key=lambda x: x[1])
    return cell[0] if distance <= 5.0 else None


def deterministic_select(
    rows: Sequence[Mapping[str, Any]], coverage: Mapping[str, tuple[datetime, datetime]],
    cells: Sequence[tuple[str, float, float]], per_year_class: int = PER_YEAR_CLASS,
) -> list[dict[str, Any]]:
    eligible = []
    for source in rows:
        timestamp = parse_utc(source["timestamp"])
        if timestamp < ARCHIVE_START or timestamp.year not in YEARS or not complete_for_horizons(source, coverage):
            continue
        cell_id = nearest_cell(float(source["latitude"]), float(source["longitude"]), cells)
        if not cell_id:
            continue
        eligible.append({**source, "_timestamp": timestamp, "cell_id": cell_id})
    selected = []
    for year in YEARS:
        for label in (0, 1):
            grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for row in eligible:
                if row["_timestamp"].year == year and int(row["fire_label"]) == label:
                    grouped[row["_timestamp"].month].append(row)
            for values in grouped.values():
                values.sort(key=lambda row: hashlib.sha256(f"{SELECTION_SEED}|{row['sample_id']}".encode()).hexdigest())
            chosen = []
            while len(chosen) < per_year_class:
                progressed = False
                for month in sorted(grouped):
                    if grouped[month] and len(chosen) < per_year_class:
                        chosen.append(grouped[month].pop(0)); progressed = True
                if not progressed:
                    raise ForecastPilotError(f"insufficient eligible samples for year={year}, label={label}")
            selected.extend(chosen)
    output = [{
        "sample_id": row["sample_id"], "sample_type": row["sample_type"],
        "timestamp": row["timestamp"], "latitude": row["latitude"], "longitude": row["longitude"],
        "cell_id": row["cell_id"], "fire_label": int(row["fire_label"]),
        "label_source": row["label_source"], "year": row["_timestamp"].year,
        "outcome_window": "target_timestamp", "selection_seed": SELECTION_SEED,
    } for row in selected]
    output.sort(key=lambda row: (row["year"], row["fire_label"], row["timestamp"], row["sample_id"]))
    expected_class = per_year_class * len(YEARS)
    expected_total = expected_class * 2
    if len(output) != expected_total or Counter(row["fire_label"] for row in output) != Counter({0: expected_class, 1: expected_class}):
        raise ForecastPilotError("sample balance invariant failed")
    return output


def snapshot_plan(samples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for sample in samples:
        target = parse_utc(sample["timestamp"])
        for horizon in HORIZONS:
            evaluation = target - timedelta(hours=horizon)
            run = select_available_run(evaluation)
            available = run + timedelta(hours=MODEL_AVAILABILITY_DELAY_HOURS)
            if available > evaluation:
                raise ForecastPilotError("forecast run availability invariant failed")
            output.append({
                **sample, "horizon_hours": horizon,
                "evaluation_time": evaluation.isoformat().replace("+00:00", "Z"),
                "forecast_target_time": target.isoformat().replace("+00:00", "Z"),
                "forecast_target_hour": target.replace(minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z"),
                "run_initialization": run.isoformat().replace("+00:00", "Z"),
                "run_available_at": available.isoformat().replace("+00:00", "Z"),
                "forecast_source": "Open-Meteo Single Runs / ECMWF IFS HRES",
            })
    return sorted(output, key=lambda row: (row["run_initialization"], row["sample_id"], row["horizon_hours"]))


class ForecastRunCache:
    def __init__(self, path: Path = CACHE_PATH): self.path = Path(path)
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path); connection.row_factory = sqlite3.Row; return connection
    def initialize(self):
        connection = self.connect()
        try:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS forecast_responses(
              request_key TEXT PRIMARY KEY,latitude REAL NOT NULL,longitude REAL NOT NULL,
              run_initialization TEXT NOT NULL,payload_json TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
              collected_at_utc TEXT NOT NULL,status TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_forecast_run ON forecast_responses(run_initialization);
            CREATE TABLE IF NOT EXISTS acquisition_runs(
              run_id TEXT PRIMARY KEY,started_at_utc TEXT NOT NULL,completed_at_utc TEXT,
              planned_requests INTEGER NOT NULL,completed_requests INTEGER NOT NULL DEFAULT 0,
              http_calls INTEGER NOT NULL DEFAULT 0,cache_hits INTEGER NOT NULL DEFAULT 0,
              failed_requests INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS forecast_run_availability(
              run_initialization TEXT PRIMARY KEY,status TEXT NOT NULL,
              checked_at_utc TEXT NOT NULL,reason TEXT);
            CREATE TABLE IF NOT EXISTS snapshot_forecast_resolutions(
              snapshot_key TEXT PRIMARY KEY,sample_id TEXT NOT NULL,horizon_hours INTEGER NOT NULL,
              original_run_initialization TEXT NOT NULL,actual_run_initialization TEXT,
              status TEXT NOT NULL,reason TEXT,resolved_at_utc TEXT NOT NULL);
            """)
            config = json.dumps({"schema": SCHEMA_VERSION, "endpoint": ENDPOINT, "model": MODEL, "variables": VARIABLES,
                                 "availability_delay_hours": MODEL_AVAILABILITY_DELAY_HOURS}, sort_keys=True)
            existing = connection.execute("SELECT value FROM metadata WHERE key='configuration'").fetchone()
            if existing and existing[0] != config: raise ForecastPilotError("forecast cache configuration is incompatible")
            connection.execute("INSERT OR IGNORE INTO metadata VALUES('configuration',?)", (config,))
            connection.execute("""
                INSERT OR IGNORE INTO forecast_run_availability(run_initialization,status,checked_at_utc,reason)
                SELECT DISTINCT run_initialization,'available',collected_at_utc,'successful cached response'
                FROM forecast_responses WHERE status='success'
            """)
            connection.commit()
        finally: connection.close()
    @staticmethod
    def key(latitude: float, longitude: float, run: datetime) -> str:
        value = f"{MODEL}|{latitude:.6f}|{longitude:.6f}|{run.isoformat()}|{','.join(VARIABLES)}"
        return hashlib.sha256(value.encode()).hexdigest()
    def has(self, latitude: float, longitude: float, run: datetime) -> bool:
        connection = self.connect()
        try: return connection.execute("SELECT 1 FROM forecast_responses WHERE request_key=?", (self.key(latitude, longitude, run),)).fetchone() is not None
        finally: connection.close()
    def load(self, latitude: float, longitude: float, run: datetime) -> dict[str, Any] | None:
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT payload_json,payload_sha256 FROM forecast_responses WHERE request_key=? AND status='success'",
                (self.key(latitude, longitude, run),),
            ).fetchone()
            if not row:
                return None
            if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                raise ForecastPilotError("cached forecast response failed integrity validation")
            return json.loads(row[0])
        except (json.JSONDecodeError, sqlite3.Error):
            raise ForecastPilotError("cached forecast response is malformed") from None
        finally:
            connection.close()
    def save(self, latitude: float, longitude: float, run: datetime, payload: Mapping[str, Any]):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")); digest = hashlib.sha256(encoded.encode()).hexdigest()
        connection = self.connect()
        try:
            connection.execute("INSERT OR IGNORE INTO forecast_responses VALUES(?,?,?,?,?,?,?,?)", (
                self.key(latitude, longitude, run), latitude, longitude, run.isoformat().replace("+00:00", "Z"), encoded, digest,
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "success")); connection.commit()
        finally: connection.close()
    def run_status(self, run: datetime) -> str | None:
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT status FROM forecast_run_availability WHERE run_initialization=?",
                (run.isoformat().replace("+00:00", "Z"),),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            connection.close()
    def record_run_status(self, run: datetime, status: str, reason: str) -> None:
        if status not in {"available", "unavailable"}:
            raise ValueError("invalid run availability status")
        connection = self.connect()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO forecast_run_availability VALUES(?,?,?,?)",
                (run.isoformat().replace("+00:00", "Z"), status,
                 datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), reason),
            )
            connection.commit()
        finally:
            connection.close()
    @staticmethod
    def snapshot_key(snapshot: Mapping[str, Any]) -> str:
        value = "|".join((str(snapshot.get("sample_id", "")), str(snapshot.get("horizon_hours", "")),
                          str(snapshot.get("forecast_target_time", "")), str(snapshot["latitude"]), str(snapshot["longitude"])))
        return hashlib.sha256(value.encode()).hexdigest()
    def resolved_run(self, snapshot: Mapping[str, Any]) -> datetime | None:
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT actual_run_initialization,status FROM snapshot_forecast_resolutions WHERE snapshot_key=?",
                (self.snapshot_key(snapshot),),
            ).fetchone()
            return parse_utc(row[0]) if row and row[1] == "available" and row[0] else None
        finally:
            connection.close()
    def save_resolution(self, snapshot: Mapping[str, Any], actual_run: datetime | None,
                        status: str, reason: str | None = None) -> None:
        connection = self.connect()
        try:
            connection.execute("INSERT OR REPLACE INTO snapshot_forecast_resolutions VALUES(?,?,?,?,?,?,?,?)", (
                self.snapshot_key(snapshot), str(snapshot.get("sample_id", "")), int(snapshot.get("horizon_hours", 0)),
                parse_utc(snapshot["run_initialization"]).isoformat().replace("+00:00", "Z"),
                actual_run.isoformat().replace("+00:00", "Z") if actual_run else None,
                status, reason, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ))
            connection.commit()
        finally:
            connection.close()


class BatchedSingleRunClient:
    def __init__(self, *, session=None, batch_size=50, minimum_interval_seconds=15.0, max_attempts=4,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.session = session or requests.Session(); self.batch_size = batch_size
        self.minimum_interval_seconds = minimum_interval_seconds; self.max_attempts = max_attempts
        self.sleep, self.clock, self.last_request = sleep, clock, None; self.http_calls = 0
    def _pace(self):
        if self.last_request is not None:
            delay = self.minimum_interval_seconds - (self.clock() - self.last_request)
            if delay > 0: self.sleep(delay)
    def fetch_batch(self, coordinates: Sequence[tuple[float, float]], run: datetime) -> list[dict[str, Any]]:
        if not coordinates or len(coordinates) > self.batch_size: raise ValueError("invalid forecast coordinate batch")
        params = {"latitude": ",".join(str(v[0]) for v in coordinates), "longitude": ",".join(str(v[1]) for v in coordinates),
                  "run": run.strftime("%Y-%m-%dT%H:%M"), "hourly": ",".join(VARIABLES), "models": MODEL,
                  "timezone": "UTC", "wind_speed_unit": "kmh", "forecast_days": 2}
        for attempt in range(1, self.max_attempts + 1):
            self._pace(); self.http_calls += 1; self.last_request = self.clock()
            try:
                response = self.session.get(ENDPOINT, params=params, headers={"User-Agent": "EcoGuard-Agents forecast-ml-pilot/1.0", "Accept": "application/json"}, timeout=60)
                status = int(response.status_code)
                response_text = str(getattr(response, "text", ""))
                if status == 400 and RUN_NOT_AVAILABLE_MESSAGE in response_text.lower():
                    raise ForecastRunUnavailableError(run)
                if status in {400, 401, 403, 404}: raise ForecastPilotError(f"forecast provider permanent HTTP {status}")
                if status == 429 or status >= 500:
                    if attempt == self.max_attempts:
                        if status == 429: raise ForecastRateLimitError("forecast provider rate limit persisted")
                        raise ForecastPilotError("forecast provider retry limit reached")
                    retry = float(response.headers.get("Retry-After", 0) or 0)
                    self.sleep(min(120.0, max(retry, 2 ** (attempt - 1)))); continue
                payload = response.json(); items = [payload] if len(coordinates) == 1 and isinstance(payload, dict) else payload
                if not isinstance(items, list) or len(items) != len(coordinates):
                    raise ForecastPilotError("forecast batch response count mismatch")
                return [validate_forecast(item, run) for item in items]
            except (requests.Timeout, requests.RequestException):
                if attempt == self.max_attempts: raise ForecastPilotError("forecast provider retry limit reached") from None
                self.sleep(min(120.0, 2 ** (attempt - 1)))
        raise AssertionError("unreachable")


def unique_requests(snapshots: Sequence[Mapping[str, Any]]) -> dict[datetime, list[tuple[float, float]]]:
    grouped: dict[datetime, set[tuple[float, float]]] = defaultdict(set)
    for row in snapshots:
        grouped[parse_utc(row["run_initialization"])].add((round(float(row["latitude"]), 6), round(float(row["longitude"]), 6)))
    return {run: sorted(values) for run, values in sorted(grouped.items())}


def fallback_runs(original_run: datetime, evaluation_time: datetime) -> list[datetime]:
    """Return deterministic standard runs, newest first, without violating availability."""
    candidates = []
    for hours in range(0, MAX_RUN_FALLBACK_HOURS + 1, STANDARD_RUN_INTERVAL_HOURS):
        candidate = original_run - timedelta(hours=hours)
        if candidate + timedelta(hours=MODEL_AVAILABILITY_DELAY_HOURS) <= evaluation_time:
            candidates.append(candidate)
    return candidates


def _target_hour(snapshot: Mapping[str, Any]) -> datetime | None:
    value = snapshot.get("forecast_target_hour") or snapshot.get("forecast_target_time")
    return parse_utc(value).replace(minute=0, second=0, microsecond=0) if value else None


def payload_contains_target(payload: Mapping[str, Any], snapshot: Mapping[str, Any]) -> bool:
    target = _target_hour(snapshot)
    if target is None:  # Backward compatibility for pre-plan cache tests.
        return True
    try:
        times = {_archive_utc(value).replace(minute=0, second=0, microsecond=0)
                 for value in payload["hourly"]["time"]}
    except (KeyError, TypeError, ValueError):
        return False
    return target in times


def acquire(snapshots: Sequence[Mapping[str, Any]], cache: ForecastRunCache, client: BatchedSingleRunClient,
            logger: Callable[[str], None] = print, max_batches: int | None = None) -> dict[str, Any]:
    cache.initialize()
    planned = len(snapshots); completed = hits = failed = batches = 0
    run_id = str(uuid.uuid4()); started = time.monotonic(); connection = cache.connect()
    connection.execute("INSERT INTO acquisition_runs(run_id,started_at_utc,planned_requests,status) VALUES(?,?,?,'running')",
                       (run_id, datetime.now(timezone.utc).isoformat(), planned)); connection.commit(); connection.close()
    stopped_for_rate_limit = False
    stopped_for_chunk_limit = False
    unresolved: list[tuple[Mapping[str, Any], int]] = []
    for snapshot in snapshots:
        actual = cache.resolved_run(snapshot)
        coordinate = (round(float(snapshot["latitude"]), 6), round(float(snapshot["longitude"]), 6))
        if actual is not None and cache.load(*coordinate, actual) is not None:
            hits += 1; completed += 1
        else:
            unresolved.append((snapshot, 0))

    while unresolved and not (stopped_for_rate_limit or stopped_for_chunk_limit):
        by_run: dict[datetime, list[tuple[Mapping[str, Any], int]]] = defaultdict(list)
        exhausted: list[Mapping[str, Any]] = []
        for snapshot, index in unresolved:
            original = parse_utc(snapshot["run_initialization"])
            evaluation = parse_utc(snapshot.get("evaluation_time") or
                                   (original + timedelta(hours=MODEL_AVAILABILITY_DELAY_HOURS)).isoformat())
            candidates = fallback_runs(original, evaluation)
            if index >= len(candidates):
                exhausted.append(snapshot)
            else:
                by_run[candidates[index]].append((snapshot, index))
        for snapshot in exhausted:
            cache.save_resolution(snapshot, None, "unavailable", "no archived model run available within 24 hours")
            failed += 1
        next_unresolved: list[tuple[Mapping[str, Any], int]] = []

        for run in sorted(by_run):
            items = by_run[run]
            if cache.run_status(run) == "unavailable":
                next_unresolved.extend((snapshot, index + 1) for snapshot, index in items)
                continue

            coordinate_items: dict[tuple[float, float], list[tuple[Mapping[str, Any], int]]] = defaultdict(list)
            for snapshot, index in items:
                coordinate = (round(float(snapshot["latitude"]), 6), round(float(snapshot["longitude"]), 6))
                coordinate_items[coordinate].append((snapshot, index))

            missing_coordinates = []
            payload_by_coordinate: dict[tuple[float, float], Mapping[str, Any]] = {}
            for coordinate in sorted(coordinate_items):
                payload = cache.load(*coordinate, run)
                if payload is None:
                    missing_coordinates.append(coordinate)
                else:
                    hits += 1; payload_by_coordinate[coordinate] = payload

            run_missing = False
            for offset in range(0, len(missing_coordinates), client.batch_size):
                if max_batches is not None and batches >= max_batches:
                    stopped_for_chunk_limit = True
                    break
                batch = missing_coordinates[offset:offset + client.batch_size]; batches += 1
                try:
                    payloads = client.fetch_batch(batch, run)
                    cache.record_run_status(run, "available", "provider returned archived model run")
                    for coordinate, payload in zip(batch, payloads):
                        cache.save(*coordinate, run, payload)
                        payload_by_coordinate[coordinate] = payload
                except ForecastRunUnavailableError:
                    cache.record_run_status(run, "unavailable", "provider reported model run unavailable")
                    logger(f"Run unavailable: {run.isoformat().replace('+00:00', 'Z')}; trying previous 6-hour run")
                    run_missing = True
                    break
                except ForecastRateLimitError as exc:
                    logger(f"ERROR: {exc}"); stopped_for_rate_limit = True; break
                except ForecastPilotError as exc:
                    logger(f"ERROR: {exc}")
                    failed += len(batch)
                logger(f"Progress: {completed}/{planned} snapshots ({completed/planned*100:.1f}%); batches={batches}; cache_hits={hits}; failed={failed}; elapsed={time.monotonic()-started:.1f}s")

            if stopped_for_rate_limit or stopped_for_chunk_limit:
                break
            if run_missing:
                next_unresolved.extend((snapshot, index + 1) for snapshot, index in items)
                continue
            for coordinate, associated in coordinate_items.items():
                payload = payload_by_coordinate.get(coordinate)
                for snapshot, index in associated:
                    if payload is not None and payload_contains_target(payload, snapshot):
                        cache.save_resolution(snapshot, run, "available")
                        completed += 1
                    elif payload is not None:
                        next_unresolved.append((snapshot, index + 1))
                    # A non-run-specific provider failure remains unresolved and can be retried on resume.
        unresolved = next_unresolved
        if not by_run:
            break
    status = "partial_rate_limited" if stopped_for_rate_limit else "partial" if failed else "chunk_complete" if stopped_for_chunk_limit else "success"; connection = cache.connect()
    connection.execute("UPDATE acquisition_runs SET completed_at_utc=?,completed_requests=?,http_calls=?,cache_hits=?,failed_requests=?,status=? WHERE run_id=?",
                       (datetime.now(timezone.utc).isoformat(), completed, client.http_calls, hits, failed, status, run_id)); connection.commit(); connection.close()
    return {"status": status, "planned_requests": planned, "completed_requests": completed, "cache_hits": hits,
            "failed_requests": failed, "logical_batches": batches, "http_calls": client.http_calls,
            "stopped_for_rate_limit": stopped_for_rate_limit, "stopped_for_chunk_limit": stopped_for_chunk_limit}


def plan() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage = archive_checkpoint_coverage((POSITIVE_CHECKPOINT, NEGATIVE_CHECKPOINT))
    samples = deterministic_select(load_dataset(), coverage, grid_cells())
    snapshots = snapshot_plan(samples); _atomic_csv(MANIFEST_PATH, samples); _atomic_csv(SNAPSHOT_PLAN_PATH, snapshots)
    return samples, snapshots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--acquire", action="store_true")
    parser.add_argument("--batch-size", type=int, default=50); parser.add_argument("--minimum-interval", type=float, default=15.0)
    parser.add_argument("--max-batches", type=int)
    args = parser.parse_args(); samples, snapshots = plan(); groups = unique_requests(snapshots)
    print(json.dumps({"samples": len(samples), "positive": sum(int(r["fire_label"]) for r in samples),
                      "negative": sum(not int(r["fire_label"]) for r in samples), "snapshots": len(snapshots),
                      "unique_coordinate_runs": sum(len(v) for v in groups.values()), "unique_runs": len(groups),
                      "projected_batches": sum(math.ceil(len(v)/args.batch_size) for v in groups.values())}, indent=2))
    if not args.acquire: return 0
    result = acquire(snapshots, ForecastRunCache(), BatchedSingleRunClient(batch_size=args.batch_size, minimum_interval_seconds=args.minimum_interval), max_batches=args.max_batches)
    print(json.dumps(result, indent=2)); return 0 if result["status"] in {"success", "chunk_complete"} else 2


if __name__ == "__main__": raise SystemExit(main())
