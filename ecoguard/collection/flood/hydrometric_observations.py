"""Collect and cache Water Authority flow and water-height observations.

The provider returns a rolling seven-day window. Recent observations have a
ten-minute resolution and older observations are hourly. This collector has no
scheduler: another system agent may invoke it every five minutes, while the
database identity prevents the repeated window from creating duplicates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import BigInteger, Column, DateTime, Float, Integer, MetaData, Table
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, insert

from ecoguard.collection.flood.hydrology_static import (
    BASE_URL,
    REQUEST_TIMEOUT_SECONDS,
)
from ecoguard.collection.flood.hydrometric_stations import (
    TOKEN_PATTERN,
    USER_AGENT,
)
from ecoguard.collection.flood.signal_rows import hydrometric_signal_records
from ecoguard.database.repositories.flood_observations import (
    upsert_flood_observations_in_session,
)


SOURCE = "water_authority_hydrometric_observations"
OBSERVATIONS_PATH = "/db_requests/get_hydro_observations_A7f3Q.php"
SOURCE_TIMEZONE = ZoneInfo("Asia/Jerusalem")
SOURCE_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
CHUNK_SIZE = 500


class HydrometricObservationError(ValueError):
    """The observation endpoint returned an unsafe or unexpected payload."""


@dataclass(frozen=True)
class HydrometricObservationBatch:
    source_url: str
    provider_latest_at: datetime
    radar_frame_count: int
    rows: list[dict[str, Any]]


# A lightweight SQLAlchemy table gives the PostgreSQL bulk INSERT its JSONB and
# timestamp types without coupling this collector to ORM models for reference
# tables that are managed directly by Alembic.
_metadata = MetaData()
HYDROMETRIC_OBSERVATIONS = Table(
    "hydrometric_observations",
    _metadata,
    Column("id", BigInteger, primary_key=True),
    Column("source_station_id", Integer, nullable=False),
    Column("hydrometric_station_id", BigInteger),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("discharge_m3s", Float),
    Column("water_height_m", Float),
    Column("source_payload", JSONB, nullable=False),
    Column("collected_at", DateTime(timezone=True), nullable=False),
)


def _source_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise HydrometricObservationError(f"{label} must be a timestamp string")
    try:
        local_time = datetime.strptime(value, SOURCE_TIMESTAMP_FORMAT).replace(
            tzinfo=SOURCE_TIMEZONE
        )
    except ValueError as error:
        raise HydrometricObservationError(
            f"{label} must use YYYY-MM-DD HH:MM:SS"
        ) from error
    return local_time.astimezone(timezone.utc)


def _station_id(value: Any) -> int:
    if isinstance(value, bool):
        raise HydrometricObservationError("station id must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise HydrometricObservationError("station id must be an integer") from error
    if result <= 0:
        raise HydrometricObservationError("station id must be positive")
    return result


def _measurement(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HydrometricObservationError(f"{label} must be numeric or null")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise HydrometricObservationError(f"{label} must be numeric or null") from error
    if not math.isfinite(result):
        raise HydrometricObservationError(f"{label} must be finite")
    return result


def parse_hydrometric_observations(payload: Any) -> HydrometricObservationBatch:
    """Normalize the provider's [discharge, water-height] values."""
    if not isinstance(payload, list) or len(payload) < 3:
        raise HydrometricObservationError(
            "observation response must contain observations, radar frames and latest time"
        )
    observations = payload[0]
    radar_frames = payload[1]
    if not isinstance(observations, dict) or not observations:
        raise HydrometricObservationError("observation response contains no observations")
    if not isinstance(radar_frames, dict):
        raise HydrometricObservationError("radar frames must be an object")

    provider_latest_at = _source_timestamp(payload[2], "provider latest time")
    rows: list[dict[str, Any]] = []
    latest_observation_at: datetime | None = None

    for source_time in sorted(observations):
        observed_at = _source_timestamp(source_time, "observation time")
        latest_observation_at = observed_at
        station_values = observations[source_time]
        if not isinstance(station_values, dict):
            raise HydrometricObservationError(
                f"observations at {source_time} must be an object"
            )

        for raw_station_id, raw_values in station_values.items():
            source_station_id = _station_id(raw_station_id)
            if not isinstance(raw_values, list) or len(raw_values) != 2:
                raise HydrometricObservationError(
                    f"station {source_station_id} at {source_time} must contain "
                    "[discharge, water height]"
                )
            discharge = _measurement(
                raw_values[0], f"station {source_station_id} discharge"
            )
            if discharge is not None and discharge < 0:
                raise HydrometricObservationError(
                    f"station {source_station_id} discharge cannot be negative"
                )
            water_height = _measurement(
                raw_values[1], f"station {source_station_id} water height"
            )
            if discharge is None and water_height is None:
                raise HydrometricObservationError(
                    f"station {source_station_id} at {source_time} has no measurement"
                )
            rows.append(
                {
                    "source_station_id": source_station_id,
                    "observed_at": observed_at,
                    "discharge_m3s": discharge,
                    "water_height_m": water_height,
                    "source_payload": raw_values,
                }
            )

    if latest_observation_at is not None and provider_latest_at < latest_observation_at:
        raise HydrometricObservationError(
            "provider latest time precedes the newest observation"
        )

    return HydrometricObservationBatch(
        source_url=f"{BASE_URL}{OBSERVATIONS_PATH}",
        provider_latest_at=provider_latest_at,
        radar_frame_count=len(radar_frames),
        rows=rows,
    )


def fetch_hydrometric_observations(
    http_session: requests.Session | None = None,
    *,
    language: str = "he",
) -> HydrometricObservationBatch:
    """Create a map session and retrieve the rolling observation window."""
    http = http_session or requests.Session()
    page_url = f"{BASE_URL}/index.php/?page=hydro_obs&lang={language}"
    page_response = http.get(
        page_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    page_response.raise_for_status()
    token_match = TOKEN_PATTERN.search(page_response.text)
    if token_match is None:
        raise HydrometricObservationError("map page did not provide a session token")

    response = http.post(
        f"{BASE_URL}{OBSERVATIONS_PATH}",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Referer": page_url,
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "X-SESSION-TOKEN": token_match.group(1),
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except requests.JSONDecodeError as error:
        raise HydrometricObservationError(
            "observation endpoint returned invalid JSON"
        ) from error
    return parse_hydrometric_observations(payload)


def _database_rows(
    batch: HydrometricObservationBatch,
    station_ids: dict[int, int],
    collected_at: datetime,
) -> tuple[list[dict[str, Any]], int]:
    rows = [
        {
            **row,
            "hydrometric_station_id": station_ids.get(row["source_station_id"]),
            "collected_at": collected_at,
        }
        for row in batch.rows
    ]
    unlinked_stations = len(
        {
            row["source_station_id"]
            for row in rows
            if row["hydrometric_station_id"] is None
        }
    )
    return rows, unlinked_stations


def persist_hydrometric_observations(
    batch: HydrometricObservationBatch,
) -> dict[str, int]:
    """Cache new observations and return received/written/link statistics."""
    from ecoguard.database.engine import Session

    collected_at = datetime.now(timezone.utc)
    written = 0
    with Session() as session:
        # A formerly unknown source id may have appeared in a later catalog
        # refresh. Repair those nullable links before inserting the new window.
        session.execute(
            text(
                """
                UPDATE hydrometric_observations AS observation
                SET hydrometric_station_id = station.id
                FROM hydrometric_stations AS station
                WHERE observation.source_station_id = station.source_station_id
                  AND observation.hydrometric_station_id IS DISTINCT FROM station.id
                """
            )
        )
        station_ids = dict(
            session.execute(
                text("SELECT source_station_id, id FROM hydrometric_stations")
            ).all()
        )
        station_metadata = {
            row["source_station_id"]: dict(row)
            for row in session.execute(
                text(
                    """
                    SELECT source_station_id, cell_id, drainage_basin_id,
                           name_he, name_en,
                           ST_Y(location::geometry) AS latitude,
                           ST_X(location::geometry) AS longitude,
                           flow_start_water_level_m,
                           flow_threshold_2y_m3s,
                           flow_threshold_5y_m3s,
                           flow_threshold_10y_m3s,
                           flow_threshold_20y_m3s,
                           flow_threshold_50y_m3s,
                           flow_threshold_100y_m3s
                    FROM hydrometric_stations
                    """
                )
            ).mappings()
        }
        rows, unlinked_stations = _database_rows(batch, station_ids, collected_at)

        for start in range(0, len(rows), CHUNK_SIZE):
            statement = insert(HYDROMETRIC_OBSERVATIONS).values(
                rows[start:start + CHUNK_SIZE]
            )
            statement = statement.on_conflict_do_update(
                constraint="hydrometric_observations_identity",
                set_={
                    "hydrometric_station_id": statement.excluded.hydrometric_station_id,
                    "discharge_m3s": statement.excluded.discharge_m3s,
                    "water_height_m": statement.excluded.water_height_m,
                    "source_payload": statement.excluded.source_payload,
                    "collected_at": statement.excluded.collected_at,
                },
                where=(
                    HYDROMETRIC_OBSERVATIONS.c.discharge_m3s.is_distinct_from(
                        statement.excluded.discharge_m3s
                    )
                    | HYDROMETRIC_OBSERVATIONS.c.water_height_m.is_distinct_from(
                        statement.excluded.water_height_m
                    )
                ),
            ).returning(HYDROMETRIC_OBSERVATIONS.c.id)
            written += len(session.execute(statement).scalars().all())

        detector_observations_written = upsert_flood_observations_in_session(
            session,
            SOURCE,
            hydrometric_signal_records(batch.rows, station_metadata),
            ingested_at=collected_at,
        )
        session.commit()

    return {
        "received": len(batch.rows),
        "written": written,
        "detector_observations_written": detector_observations_written,
        "unlinked_stations": unlinked_stations,
    }


def load_hydrometric_observations(
    http_session: requests.Session | None = None,
) -> dict[str, int]:
    """Fetch and cache one rolling window; scheduling belongs to the caller."""
    from ecoguard.database.repositories.collector_runs import log_finish, log_start

    run_id = log_start(SOURCE)
    try:
        result = persist_hydrometric_observations(
            fetch_hydrometric_observations(http_session)
        )
        log_finish(run_id, status="ok", rows_written=result["written"])
        return result
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise
