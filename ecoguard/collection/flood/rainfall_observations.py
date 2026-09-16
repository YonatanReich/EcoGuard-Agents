"""Collect and cache numeric Water Authority rain-gauge observations.

The provider returns a rolling window of ten-minute measurements, rain-station
metadata, and its current accumulation summaries. This collector has no
scheduler: another system agent may invoke it every five minutes. The database
identity makes repeated windows idempotent.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import BigInteger, Column, DateTime, Float, MetaData, Table, text
from sqlalchemy.dialects.postgresql import JSONB, insert

from ecoguard.collection.flood.hydrology_static import (
    BASE_URL,
    REQUEST_TIMEOUT_SECONDS,
)
from ecoguard.collection.flood.hydrometric_stations import (
    TOKEN_PATTERN,
    USER_AGENT,
)
from ecoguard.collection.base import cell_for
from ecoguard.collection.flood.signal_rows import rainfall_signal_records
from ecoguard.database.repositories.flood_observations import (
    upsert_flood_observations_in_session,
)


SOURCE = "water_authority_rainfall_observations"
OBSERVATIONS_PATH = "/db_requests/get_rain_observations_A7f3Q.php"
SOURCE_TIMEZONE = ZoneInfo("Asia/Jerusalem")
SOURCE_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
CHUNK_SIZE = 500


class RainfallObservationError(ValueError):
    """The rain endpoint returned an unsafe or unexpected payload."""


@dataclass(frozen=True)
class RainfallObservationBatch:
    source_url: str
    provider_latest_at: datetime
    provider_response_at: datetime | None
    stations: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    accumulations: list[dict[str, Any]]


# Lightweight SQLAlchemy tables provide the PostgreSQL insert statements with
# the correct JSONB and timezone-aware timestamp types without adding ORM models
# for these ingestion-only tables.
_metadata = MetaData()
RAINFALL_OBSERVATIONS = Table(
    "rainfall_observations",
    _metadata,
    Column("id", BigInteger, primary_key=True),
    Column("source_station_id", BigInteger, nullable=False),
    Column("rain_station_id", BigInteger),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("rainfall_mm", Float, nullable=False),
    Column("source_payload", JSONB, nullable=False),
    Column("collected_at", DateTime(timezone=True), nullable=False),
)
RAINFALL_ACCUMULATIONS = Table(
    "rainfall_accumulations",
    _metadata,
    Column("id", BigInteger, primary_key=True),
    Column("source_station_id", BigInteger, nullable=False),
    Column("rain_station_id", BigInteger),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("rainfall_6h_mm", Float),
    Column("rainfall_12h_mm", Float),
    Column("rainfall_24h_mm", Float),
    Column("rainfall_month_mm", Float),
    Column("rainfall_season_mm", Float),
    # Missing hourly detail must be SQL NULL. JSONB's default serializes Python
    # None as JSON null, which violates the database's object-or-NULL contract.
    Column("hourly_values", JSONB(none_as_null=True)),
    Column("source_payload", JSONB, nullable=False),
    Column("collected_at", DateTime(timezone=True), nullable=False),
)


RAIN_STATION_UPSERT = text(
    """
    INSERT INTO rain_stations
      (source_station_id, name_he, name_en, location, cell_id, source_owner_id,
       owner_id, is_active, source_metadata, synced_at)
    VALUES
      (:source_station_id, :name_he, :name_en,
       ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
       :cell_id, :source_owner_id, :owner_id, true,
       CAST(:source_metadata AS jsonb), :synced_at)
    ON CONFLICT ON CONSTRAINT rain_stations_identity DO UPDATE SET
      name_he = EXCLUDED.name_he,
      name_en = EXCLUDED.name_en,
      location = EXCLUDED.location,
      cell_id = EXCLUDED.cell_id,
      source_owner_id = EXCLUDED.source_owner_id,
      owner_id = EXCLUDED.owner_id,
      is_active = true,
      source_metadata = EXCLUDED.source_metadata,
      synced_at = EXCLUDED.synced_at
    """
)


def _source_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise RainfallObservationError(f"{label} must be a timestamp string")
    try:
        local_time = datetime.strptime(value, SOURCE_TIMESTAMP_FORMAT).replace(
            tzinfo=SOURCE_TIMEZONE
        )
    except ValueError as error:
        raise RainfallObservationError(
            f"{label} must use YYYY-MM-DD HH:MM:SS"
        ) from error
    return local_time.astimezone(timezone.utc)


def _station_id(value: Any) -> int:
    if isinstance(value, bool):
        raise RainfallObservationError("station id must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise RainfallObservationError("station id must be an integer") from error
    if result <= 0:
        raise RainfallObservationError("station id must be positive")
    return result


def _number(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise RainfallObservationError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise RainfallObservationError(f"{label} must be numeric") from error
    if not math.isfinite(result):
        raise RainfallObservationError(f"{label} must be finite")
    return result


def _rainfall(value: Any, label: str) -> float:
    result = _number(value, label)
    if result < 0:
        raise RainfallObservationError(f"{label} cannot be negative")
    return result


def _optional_rainfall(
    values: dict[str, Any], key: str, label: str
) -> float | None:
    value = values.get(key)
    return None if value is None else _rainfall(value, label)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RainfallObservationError(f"{label} must be an object")
    return value


def parse_rainfall_observations(payload: Any) -> RainfallObservationBatch:
    """Validate and normalize rain stations, measurements and summaries."""
    if not isinstance(payload, list) or len(payload) < 4:
        raise RainfallObservationError(
            "rain response must contain observations, stations, summaries and latest time"
        )

    raw_observations = _mapping(payload[0], "rain observations")
    raw_stations = _mapping(payload[1], "rain stations")
    raw_accumulations = _mapping(payload[2], "rain accumulations")
    if not raw_stations:
        raise RainfallObservationError("rain response contains no station metadata")

    provider_latest_at = _source_timestamp(payload[3], "provider latest time")
    provider_response_at = (
        _source_timestamp(payload[4], "provider response time")
        if len(payload) > 4 and payload[4] is not None
        else None
    )

    stations: list[dict[str, Any]] = []
    station_ids: set[int] = set()
    for raw_station_id, raw_station in raw_stations.items():
        source_station_id = _station_id(raw_station_id)
        if source_station_id in station_ids:
            raise RainfallObservationError(
                f"duplicate rain station id {source_station_id}"
            )
        station_ids.add(source_station_id)
        station = _mapping(raw_station, f"rain station {source_station_id}")
        name_he = _optional_text(station.get("name_he"))
        name_en = _optional_text(station.get("name"))
        if name_he is None and name_en is None:
            raise RainfallObservationError(
                f"rain station {source_station_id} has no name"
            )

        latitude = _number(
            station.get("lat"), f"rain station {source_station_id} latitude"
        )
        longitude = _number(
            station.get("lon"), f"rain station {source_station_id} longitude"
        )
        if not -90 <= latitude <= 90:
            raise RainfallObservationError(
                f"rain station {source_station_id} latitude is out of range"
            )
        if not -180 <= longitude <= 180:
            raise RainfallObservationError(
                f"rain station {source_station_id} longitude is out of range"
            )

        stations.append(
            {
                "source_station_id": source_station_id,
                "name_he": name_he,
                "name_en": name_en,
                "latitude": latitude,
                "longitude": longitude,
                "source_owner_id": _station_id(station.get("owner_id")),
                "source_metadata": station,
            }
        )

    rows: list[dict[str, Any]] = []
    newest_observation_at: datetime | None = None
    for raw_station_id, raw_series in raw_observations.items():
        source_station_id = _station_id(raw_station_id)
        series = _mapping(raw_series, f"rain station {source_station_id} observations")
        for source_time in sorted(series):
            observed_at = _source_timestamp(source_time, "rain observation time")
            newest_observation_at = max(
                observed_at, newest_observation_at or observed_at
            )
            rainfall_mm = _rainfall(
                series[source_time],
                f"rain station {source_station_id} observation at {source_time}",
            )
            rows.append(
                {
                    "source_station_id": source_station_id,
                    "observed_at": observed_at,
                    "rainfall_mm": rainfall_mm,
                    "source_payload": series[source_time],
                }
            )

    if newest_observation_at is not None and provider_latest_at < newest_observation_at:
        raise RainfallObservationError(
            "provider latest time precedes the newest rain observation"
        )

    accumulations: list[dict[str, Any]] = []
    for raw_station_id, raw_summary in raw_accumulations.items():
        source_station_id = _station_id(raw_station_id)
        summary = _mapping(
            raw_summary, f"rain station {source_station_id} accumulation"
        )
        raw_hourly = summary.get("24h")
        hourly_values: dict[str, float] | None = None
        if raw_hourly is not None:
            hourly_values = {}
            for source_time, raw_value in _mapping(
                raw_hourly, f"rain station {source_station_id} hourly values"
            ).items():
                hourly_at = _source_timestamp(source_time, "hourly rain time")
                if hourly_at > provider_latest_at:
                    raise RainfallObservationError(
                        f"rain station {source_station_id} has a future hourly value"
                    )
                hourly_values[source_time] = _rainfall(
                    raw_value,
                    f"rain station {source_station_id} hourly value at {source_time}",
                )

        accumulations.append(
            {
                "source_station_id": source_station_id,
                "as_of": provider_latest_at,
                # Missing keys mean that the provider cannot calculate that
                # period for this station yet. Preserve that distinction as
                # NULL rather than fabricating a zero or dropping the station.
                "rainfall_6h_mm": _optional_rainfall(
                    summary, "6", f"rain station {source_station_id} 6-hour rain"
                ),
                "rainfall_12h_mm": _optional_rainfall(
                    summary, "12", f"rain station {source_station_id} 12-hour rain"
                ),
                "rainfall_24h_mm": _optional_rainfall(
                    summary, "24", f"rain station {source_station_id} 24-hour rain"
                ),
                "rainfall_month_mm": _optional_rainfall(
                    summary,
                    "month",
                    f"rain station {source_station_id} monthly rain",
                ),
                "rainfall_season_mm": _optional_rainfall(
                    summary,
                    "year",
                    f"rain station {source_station_id} seasonal rain",
                ),
                "hourly_values": hourly_values,
                "source_payload": summary,
            }
        )

    return RainfallObservationBatch(
        source_url=f"{BASE_URL}{OBSERVATIONS_PATH}",
        provider_latest_at=provider_latest_at,
        provider_response_at=provider_response_at,
        stations=stations,
        rows=rows,
        accumulations=accumulations,
    )


def fetch_rainfall_observations(
    http_session: requests.Session | None = None,
    *,
    language: str = "he",
) -> RainfallObservationBatch:
    """Create a map session and retrieve numeric rain-gauge data."""
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
        raise RainfallObservationError("map page did not provide a session token")

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
        raise RainfallObservationError(
            "rain observation endpoint returned invalid JSON"
        ) from error
    return parse_rainfall_observations(payload)


def _database_rows(
    batch: RainfallObservationBatch,
    station_ids: dict[int, int],
    collected_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    observations = [
        {
            **row,
            "rain_station_id": station_ids.get(row["source_station_id"]),
            "collected_at": collected_at,
        }
        for row in batch.rows
    ]
    accumulations = [
        {
            **row,
            "rain_station_id": station_ids.get(row["source_station_id"]),
            "collected_at": collected_at,
        }
        for row in batch.accumulations
    ]
    unlinked_stations = len(
        {
            row["source_station_id"]
            for row in [*observations, *accumulations]
            if row["rain_station_id"] is None
        }
    )
    return observations, accumulations, unlinked_stations


def _rainfall_observation_upsert(rows: list[dict[str, Any]]) -> Any:
    """Insert new samples and apply genuine corrections to existing samples."""
    statement = insert(RAINFALL_OBSERVATIONS).values(rows)
    return statement.on_conflict_do_update(
        constraint="rainfall_observations_identity",
        set_={
            "rain_station_id": statement.excluded.rain_station_id,
            "rainfall_mm": statement.excluded.rainfall_mm,
            "source_payload": statement.excluded.source_payload,
            # For a corrected sample this becomes the time at which the
            # corrected value was collected. Identical repeats do not reach
            # this update and therefore leave collected_at unchanged.
            "collected_at": statement.excluded.collected_at,
        },
        where=RAINFALL_OBSERVATIONS.c.rainfall_mm.is_distinct_from(
            statement.excluded.rainfall_mm
        ),
    ).returning(RAINFALL_OBSERVATIONS.c.id)


def persist_rainfall_observations(
    batch: RainfallObservationBatch,
) -> dict[str, int]:
    """Synchronize rain stations and cache one provider observation window."""
    from ecoguard.database.engine import Session

    collected_at = datetime.now(timezone.utc)
    observations_written = 0
    with Session() as session:
        owner_ids = dict(
            session.execute(
                text("SELECT source_owner_id, id FROM water_authority_station_owners")
            ).all()
        )
        station_rows = [
            {
                **station,
                "cell_id": cell_for(station["latitude"], station["longitude"]),
                "owner_id": owner_ids.get(station["source_owner_id"]),
                "source_metadata": json.dumps(
                    station["source_metadata"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "synced_at": collected_at,
            }
            for station in batch.stations
        ]

        # The endpoint's metadata object is the current complete rain-station
        # catalog. Preserve missing rows for history but exclude them from
        # current-station queries until they reappear.
        session.execute(text("UPDATE rain_stations SET is_active = false"))
        session.execute(RAIN_STATION_UPSERT, station_rows)

        station_ids = dict(
            session.execute(
                text("SELECT source_station_id, id FROM rain_stations")
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
                           ST_X(location::geometry) AS longitude
                    FROM rain_stations
                    """
                )
            ).mappings()
        }

        # Repair nullable links if a previously unknown source station has now
        # appeared in the provider's metadata.
        session.execute(
            text(
                """
                UPDATE rainfall_observations AS observation
                SET rain_station_id = station.id
                FROM rain_stations AS station
                WHERE observation.source_station_id = station.source_station_id
                  AND observation.rain_station_id IS DISTINCT FROM station.id
                """
            )
        )
        session.execute(
            text(
                """
                UPDATE rainfall_accumulations AS accumulation
                SET rain_station_id = station.id
                FROM rain_stations AS station
                WHERE accumulation.source_station_id = station.source_station_id
                  AND accumulation.rain_station_id IS DISTINCT FROM station.id
                """
            )
        )

        observations, accumulations, unlinked_stations = _database_rows(
            batch, station_ids, collected_at
        )
        for start in range(0, len(observations), CHUNK_SIZE):
            statement = _rainfall_observation_upsert(
                observations[start : start + CHUNK_SIZE]
            )
            observations_written += len(session.execute(statement).scalars().all())

        detector_observations_written = upsert_flood_observations_in_session(
            session,
            SOURCE,
            rainfall_signal_records(batch.rows, station_metadata),
            ingested_at=collected_at,
        )

        for start in range(0, len(accumulations), CHUNK_SIZE):
            statement = insert(RAINFALL_ACCUMULATIONS).values(
                accumulations[start : start + CHUNK_SIZE]
            )
            statement = statement.on_conflict_do_update(
                constraint="rainfall_accumulations_identity",
                set_={
                    "rain_station_id": statement.excluded.rain_station_id,
                    "as_of": statement.excluded.as_of,
                    "rainfall_6h_mm": statement.excluded.rainfall_6h_mm,
                    "rainfall_12h_mm": statement.excluded.rainfall_12h_mm,
                    "rainfall_24h_mm": statement.excluded.rainfall_24h_mm,
                    "rainfall_month_mm": statement.excluded.rainfall_month_mm,
                    "rainfall_season_mm": statement.excluded.rainfall_season_mm,
                    "hourly_values": statement.excluded.hourly_values,
                    "source_payload": statement.excluded.source_payload,
                    "collected_at": statement.excluded.collected_at,
                },
                # Concurrent or delayed collectors must never replace a newer
                # provider summary with an older rolling window.
                where=RAINFALL_ACCUMULATIONS.c.as_of <= statement.excluded.as_of,
            )
            session.execute(statement)

        session.commit()

    return {
        "stations": len(batch.stations),
        "observations_received": len(batch.rows),
        "observations_written": observations_written,
        "detector_observations_written": detector_observations_written,
        "accumulations": len(batch.accumulations),
        "unlinked_stations": unlinked_stations,
        "unlinked_owners": len(
            {
                station["source_owner_id"]
                for station in batch.stations
                if station["source_owner_id"] not in owner_ids
            }
        ),
    }


def load_rainfall_observations(
    http_session: requests.Session | None = None,
) -> dict[str, int]:
    """Fetch and cache one rolling window; scheduling belongs to the caller."""
    from ecoguard.database.repositories.collector_runs import log_finish, log_start

    run_id = log_start(SOURCE)
    try:
        result = persist_rainfall_observations(
            fetch_rainfall_observations(http_session)
        )
        log_finish(
            run_id,
            status="ok",
            rows_written=result["observations_written"],
        )
        return result
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise
