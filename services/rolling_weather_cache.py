"""Persistent, resumable hourly weather cache for fire-risk grid cells."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from services.open_meteo_hourly_client import HOURLY_VARIABLES, HourlyProviderError, OpenMeteoHourlyClient
from services.service_area import DEFAULT_SERVICE_AREA_PATH, ServiceArea
from services.weather_feature_calculator import compute_features


DEFAULT_CACHE_PATH = Path("data/generated/fire_risk_weather_cache.sqlite")
DEFAULT_GRID_PATH = Path("data/generated/fire_risk_grid.sqlite")
SCHEMA_VERSION = 1
RETENTION_HOURS = 216
SOURCE_KIND = "past_hourly"


class WeatherCacheError(RuntimeError):
    pass


def _hour(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise WeatherCacheError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def weather_node_id(latitude: float, longitude: float) -> str:
    identity = f"open-meteo|UTC|{latitude:.6f}|{longitude:.6f}|{','.join(HOURLY_VARIABLES)}"
    return "om-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def missing_hour_ranges(existing: Iterable[datetime], start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    present = {_hour(value) for value in existing}
    missing, cursor = [], _hour(start)
    while cursor <= _hour(end):
        if cursor not in present:
            range_start = cursor
            while cursor <= _hour(end) and cursor not in present:
                cursor += timedelta(hours=1)
            missing.append((range_start, cursor - timedelta(hours=1)))
        else:
            cursor += timedelta(hours=1)
    return missing


class RollingWeatherCache:
    def __init__(self, path: Path = DEFAULT_CACHE_PATH, *, retention_hours: int = RETENTION_HOURS):
        if retention_hours < 168:
            raise ValueError("retention must cover the model's seven-day window")
        self.path, self.retention_hours = Path(path), retention_hours
        self._read_connection: sqlite3.Connection | None = None

    @contextmanager
    def read_session(self):
        """Reuse one read connection for a deterministic bulk feature scan."""
        if self._read_connection is not None:
            yield
            return
        connection = self.connect(); self._read_connection = connection
        try:
            yield
        finally:
            self._read_connection = None
            connection.close()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        connection = self.connect()
        try:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS weather_cache_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS weather_nodes (
                weather_node_id TEXT PRIMARY KEY, query_latitude REAL NOT NULL, query_longitude REAL NOT NULL,
                provider_latitude REAL NOT NULL, provider_longitude REAL NOT NULL, provider_elevation REAL,
                provider_timezone TEXT NOT NULL, created_at_utc TEXT NOT NULL, last_success_at_utc TEXT,
                status TEXT NOT NULL, last_error TEXT);
            CREATE TABLE IF NOT EXISTS grid_weather_nodes (
                cell_id TEXT PRIMARY KEY, weather_node_id TEXT NOT NULL, mapping_method TEXT NOT NULL,
                mapping_version INTEGER NOT NULL, mapped_at_utc TEXT NOT NULL,
                FOREIGN KEY(weather_node_id) REFERENCES weather_nodes(weather_node_id));
            CREATE INDEX IF NOT EXISTS idx_grid_weather_node ON grid_weather_nodes(weather_node_id);
            CREATE TABLE IF NOT EXISTS hourly_weather (
                weather_node_id TEXT NOT NULL, valid_time_utc TEXT NOT NULL,
                temperature_2m REAL, relative_humidity_2m REAL, precipitation REAL, rain REAL,
                wind_speed_10m REAL, wind_direction_10m REAL, wind_gusts_10m REAL,
                source_kind TEXT NOT NULL, provider TEXT NOT NULL, collected_at_utc TEXT NOT NULL,
                data_status TEXT NOT NULL,
                PRIMARY KEY(weather_node_id, valid_time_utc, source_kind),
                FOREIGN KEY(weather_node_id) REFERENCES weather_nodes(weather_node_id));
            CREATE INDEX IF NOT EXISTS idx_hourly_node_time ON hourly_weather(weather_node_id, valid_time_utc);
            CREATE TABLE IF NOT EXISTS weather_update_runs (
                run_id TEXT PRIMARY KEY, started_at_utc TEXT NOT NULL, completed_at_utc TEXT,
                active_grid_cells INTEGER NOT NULL, unique_weather_nodes INTEGER NOT NULL DEFAULT 0,
                batches_requested INTEGER NOT NULL DEFAULT 0, inserted_hours INTEGER NOT NULL DEFAULT 0,
                cache_hits INTEGER NOT NULL DEFAULT 0, failed_nodes INTEGER NOT NULL DEFAULT 0,
                stale_nodes INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, safe_error TEXT);
            """)
            config = {
                "schema_version": SCHEMA_VERSION, "provider": "Open-Meteo Forecast API",
                "timezone": "UTC", "variables": list(HOURLY_VARIABLES),
                "retention_hours": self.retention_hours, "source_kind": SOURCE_KIND,
            }
            encoded = json.dumps(config, sort_keys=True, separators=(",", ":"))
            current = connection.execute("SELECT value FROM weather_cache_metadata WHERE key='configuration'").fetchone()
            if current and current[0] != encoded:
                raise WeatherCacheError("weather cache configuration is incompatible")
            connection.execute("INSERT OR IGNORE INTO weather_cache_metadata(key,value) VALUES('configuration',?)", (encoded,))
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _active_cells(grid_path: Path) -> list[tuple[str, float, float]]:
        if not Path(grid_path).exists():
            raise WeatherCacheError(f"grid database is missing: {grid_path}")
        connection = sqlite3.connect(grid_path)
        try:
            return [(str(row[0]), float(row[1]), float(row[2])) for row in connection.execute(
                "SELECT cell_id,latitude,longitude FROM risk_grid_cells WHERE active=1 ORDER BY cell_id"
            )]
        except sqlite3.Error:
            raise WeatherCacheError("grid database schema is incompatible") from None
        finally:
            connection.close()

    @staticmethod
    def _insert_response(
        connection: sqlite3.Connection, node_id: str, response: dict[str, Any],
        requested_start: datetime, requested_end: datetime, collected_at: str,
    ) -> int:
        hourly = response["hourly"]
        before = connection.total_changes
        for index, value in enumerate(hourly["time"]):
            timestamp = _parse(value)
            if not requested_start <= timestamp <= requested_end:
                continue
            values = [hourly[variable][index] for variable in HOURLY_VARIABLES]
            connection.execute(
                """INSERT OR IGNORE INTO hourly_weather VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (node_id, _text(timestamp), *values, SOURCE_KIND, "Open-Meteo Forecast API", collected_at, response["status"]),
            )
        return connection.total_changes - before

    def update(
        self, *, grid_path: Path = DEFAULT_GRID_PATH, client: OpenMeteoHourlyClient,
        now: datetime | None = None, service_area_path: Path | str = DEFAULT_SERVICE_AREA_PATH,
    ) -> dict[str, Any]:
        self.initialize()
        current = _hour(now or datetime.now(timezone.utc))
        desired_end = current - timedelta(hours=1)
        desired_start = desired_end - timedelta(hours=self.retention_hours - 1)
        all_active = self._active_cells(grid_path)
        service_area = ServiceArea(service_area_path)
        active = [cell for cell in all_active if service_area.includes_cell(cell[1], cell[2])]
        active_ids = {cell[0] for cell in active}
        run_id, started = str(uuid.uuid4()), _text(datetime.now(timezone.utc))
        metrics = {
            "active_grid_cells_before_service_area": len(all_active),
            "active_grid_cells": len(active),
            "service_area_excluded_cells": len(all_active) - len(active),
            "batches_requested": 0, "inserted_hours": 0, "cache_hits": 0, "failed_nodes": 0,
        }
        failed_targets: set[str] = set()
        connection = self.connect()
        try:
            connection.execute(
                "INSERT INTO weather_update_runs(run_id,started_at_utc,active_grid_cells,status) VALUES(?,?,?,'running')",
                (run_id, started, len(active)),
            )
            mapped = {
                row[0] for row in connection.execute("SELECT cell_id FROM grid_weather_nodes")
                if row[0] in active_ids
            }
            pending = [cell for cell in active if cell[0] not in mapped]
            for offset in range(0, len(pending), client.batch_size):
                batch = pending[offset:offset + client.batch_size]
                metrics["batches_requested"] += 1
                try:
                    responses = client.fetch_range([(row[1], row[2]) for row in batch], desired_start, desired_end)
                except HourlyProviderError:
                    failed_targets.update(row[0] for row in batch)
                    continue
                collected = _text(datetime.now(timezone.utc))
                for cell, response in zip(batch, responses):
                    node_id = weather_node_id(response["provider_latitude"], response["provider_longitude"])
                    connection.execute(
                        """INSERT OR IGNORE INTO weather_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (node_id, cell[1], cell[2], response["provider_latitude"], response["provider_longitude"],
                         response.get("provider_elevation"), "UTC", collected, collected, "available", None),
                    )
                    connection.execute(
                        "INSERT OR REPLACE INTO grid_weather_nodes VALUES(?,?,?,1,?)",
                        (cell[0], node_id, "provider_returned_coordinate", collected),
                    )
                    metrics["inserted_hours"] += self._insert_response(connection, node_id, response, desired_start, desired_end, collected)
                connection.commit()

            nodes = sorted({
                row[1] for row in connection.execute(
                    "SELECT cell_id,weather_node_id FROM grid_weather_nodes"
                ) if row[0] in active_ids
            })
            ranges: dict[tuple[datetime, datetime], list[str]] = defaultdict(list)
            for node_id in nodes:
                existing = [_parse(row[0]) for row in connection.execute(
                    "SELECT valid_time_utc FROM hourly_weather WHERE weather_node_id=? AND source_kind=? AND valid_time_utc BETWEEN ? AND ?",
                    (node_id, SOURCE_KIND, _text(desired_start), _text(desired_end)),
                )]
                gaps = missing_hour_ranges(existing, desired_start, desired_end)
                if not gaps:
                    metrics["cache_hits"] += 1
                for gap in gaps:
                    ranges[gap].append(node_id)

            successful_nodes: set[str] = set()
            for (gap_start, gap_end), node_ids in sorted(ranges.items()):
                for offset in range(0, len(node_ids), client.batch_size):
                    batch_ids = node_ids[offset:offset + client.batch_size]
                    coordinates = []
                    for node_id in batch_ids:
                        row = connection.execute("SELECT provider_latitude,provider_longitude FROM weather_nodes WHERE weather_node_id=?", (node_id,)).fetchone()
                        coordinates.append((row[0], row[1]))
                    metrics["batches_requested"] += 1
                    try:
                        responses = client.fetch_range(coordinates, gap_start, gap_end)
                    except HourlyProviderError:
                        failed_targets.update(batch_ids)
                        continue
                    collected = _text(datetime.now(timezone.utc))
                    for node_id, response in zip(batch_ids, responses):
                        returned_id = weather_node_id(response["provider_latitude"], response["provider_longitude"])
                        if returned_id != node_id:
                            failed_targets.add(node_id)
                            continue
                        metrics["inserted_hours"] += self._insert_response(connection, node_id, response, gap_start, gap_end, collected)
                        connection.execute("UPDATE weather_nodes SET last_success_at_utc=?,status='available',last_error=NULL WHERE weather_node_id=?", (collected, node_id))
                        successful_nodes.add(node_id)
                    connection.commit()

            cutoff = desired_start
            for node_id in successful_nodes:
                connection.execute("DELETE FROM hourly_weather WHERE weather_node_id=? AND valid_time_utc<?", (node_id, _text(cutoff)))
            stale = 0
            for node_id in nodes:
                count = connection.execute(
                    "SELECT COUNT(*) FROM hourly_weather WHERE weather_node_id=? AND source_kind=? AND valid_time_utc BETWEEN ? AND ?",
                    (node_id, SOURCE_KIND, _text(desired_start), _text(desired_end)),
                ).fetchone()[0]
                if count != self.retention_hours:
                    stale += 1
                    connection.execute("UPDATE weather_nodes SET status='stale',last_error='incomplete_hourly_coverage' WHERE weather_node_id=?", (node_id,))
            metrics.update({
                "unique_weather_nodes": len(nodes), "reuse_ratio": round(len(active) / len(nodes), 3) if nodes else 0.0,
                "failed_nodes": len(failed_targets), "stale_nodes": stale,
                "status": "partial" if failed_targets or stale else "success",
            })
            connection.execute(
                """UPDATE weather_update_runs SET completed_at_utc=?,unique_weather_nodes=?,batches_requested=?,inserted_hours=?,
                cache_hits=?,failed_nodes=?,stale_nodes=?,status=? WHERE run_id=?""",
                (_text(datetime.now(timezone.utc)), len(nodes), metrics["batches_requested"], metrics["inserted_hours"],
                 metrics["cache_hits"], metrics["failed_nodes"], stale, metrics["status"], run_id),
            )
            connection.commit()
            return metrics
        finally:
            connection.close()

    def features_for_cell(self, cell_id: str, evaluation_time: datetime) -> dict[str, Any]:
        evaluation = evaluation_time.astimezone(timezone.utc)
        required_end = _hour(evaluation) - timedelta(hours=1)
        required_start = required_end - timedelta(hours=167)
        connection = self._read_connection or self.connect()
        owns_connection = self._read_connection is None
        try:
            mapping = connection.execute("SELECT weather_node_id FROM grid_weather_nodes WHERE cell_id=?", (cell_id,)).fetchone()
            if not mapping:
                features, status = compute_features({}, evaluation)
                return {"status": status, "reason": "weather_cell_unmapped", "weather_node_id": None, "features": features}
            node_id = mapping[0]
            start = evaluation - timedelta(hours=self.retention_hours)
            rows = connection.execute(
                """SELECT valid_time_utc,temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m,
                wind_direction_10m,wind_gusts_10m,data_status FROM hourly_weather
                WHERE weather_node_id=? AND source_kind=? AND valid_time_utc>=? AND valid_time_utc<? ORDER BY valid_time_utc""",
                (node_id, SOURCE_KIND, _text(start), _text(evaluation)),
            ).fetchall()
        finally:
            if owns_connection:
                connection.close()
        hourly = {"time": [row[0] for row in rows]}
        for index, variable in enumerate(HOURLY_VARIABLES, start=1):
            hourly[variable] = [row[index] for row in rows]
        available = {_parse(value) for value in hourly["time"]}
        expected = {required_start + timedelta(hours=index) for index in range(168)}
        missing_hours = len(expected - available)
        source_status = "success" if rows and all(row[8] == "success" for row in rows) else "partial"
        features, status = compute_features({"status": source_status, "hourly": hourly}, evaluation)
        if missing_hours or status != "success":
            return {
                "status": "stale", "reason": "weather_history_incomplete", "missing_hours": missing_hours,
                "weather_node_id": node_id, "features": features,
            }
        return {"status": "success", "reason": None, "missing_hours": 0, "weather_node_id": node_id, "features": features}
