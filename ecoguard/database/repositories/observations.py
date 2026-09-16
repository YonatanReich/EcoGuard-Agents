"""Shared raw-observation writes and bounded, source-scoped reads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

from geoalchemy2 import Geometry, WKTElement
from sqlalchemy import and_, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from ecoguard.database.engine import Session
from ecoguard.database.models import Observation

# One statement per chunk. A national weather sweep is ~1,200 rows, which is
# comfortable in a single INSERT, but FIRMS after a bad fire day is not.
CHUNK_SIZE = 500
DEFAULT_READ_BATCH_SIZE = 500
MAX_READ_BATCH_SIZE = 5000
AIR_POLLUTION_SOURCE = "air_pollution"
AIR_POLLUTION_TREND_LOOKBACK_MINUTES = 120
MAX_AIR_POLLUTION_HISTORY_ROWS = 100


def _aware(value: datetime | None, *, name: str) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must carry a UTC offset")
    return value.astimezone(timezone.utc) if value is not None else None


def observation_batch_statement(
    source: str,
    *,
    ingested_after: datetime | None = None,
    after_id: int | None = None,
    ingested_through: datetime | None = None,
    limit: int = DEFAULT_READ_BATCH_SIZE,
):
    """Build a bounded, stable read of one source's ingestion stream.

    ``after_id`` disambiguates pagination when several rows share one
    ``ingested_at`` batch timestamp. It is meaningful only together with
    ``ingested_after``; no cursor state is stored by this repository.
    """

    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be non-empty")
    if type(limit) is not int or not 1 <= limit <= MAX_READ_BATCH_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_READ_BATCH_SIZE}")
    if after_id is not None and (
        ingested_after is None or type(after_id) is not int or after_id < 0
    ):
        raise ValueError("after_id requires ingested_after and must be non-negative")
    lower = _aware(ingested_after, name="ingested_after")
    upper = _aware(ingested_through, name="ingested_through")
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("ingested_after cannot exceed ingested_through")

    point = cast(Observation.location, Geometry(geometry_type="POINT", srid=4326))
    statement = select(
        Observation.id,
        Observation.source,
        Observation.cell_id,
        Observation.observed_at,
        Observation.ingested_at,
        Observation.payload,
        func.ST_Y(point).label("latitude"),
        func.ST_X(point).label("longitude"),
    ).where(Observation.source == source)
    if lower is not None:
        if after_id is None:
            statement = statement.where(Observation.ingested_at > lower)
        else:
            statement = statement.where(or_(
                Observation.ingested_at > lower,
                and_(
                    Observation.ingested_at == lower,
                    Observation.id > after_id,
                ),
            ))
    if upper is not None:
        statement = statement.where(Observation.ingested_at <= upper)
    return statement.order_by(Observation.ingested_at, Observation.id).limit(limit)


def read_observations_batch(
    source: str,
    *,
    ingested_after: datetime | None = None,
    after_id: int | None = None,
    ingested_through: datetime | None = None,
    limit: int = DEFAULT_READ_BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Read one bounded ordered batch; performs exactly one SELECT and no writes."""

    statement = observation_batch_statement(
        source,
        ingested_after=ingested_after,
        after_id=after_id,
        ingested_through=ingested_through,
        limit=limit,
    )
    with Session() as session:
        return [dict(row) for row in session.execute(statement).mappings().all()]


def air_pollution_series_cell_id(
    station_id: str,
    channel_id: str,
    pollutant: str,
    unit: str,
) -> str:
    """Build the collector's canonical source-local Air Pollution identity."""

    parts = (station_id, channel_id, pollutant, unit)
    if any(not isinstance(part, str) or not part.strip() for part in parts):
        raise ValueError("Air Pollution series identity fields must be non-empty")
    encoded = ":".join(quote(part, safe="") for part in parts)
    return f"ministry:{encoded}"


def air_pollution_series_history_statement(
    *,
    station_id: str,
    channel_id: str,
    pollutant: str,
    unit: str,
    prediction_time: datetime,
    lookback_minutes: int = AIR_POLLUTION_TREND_LOOKBACK_MINUTES,
    limit: int = MAX_AIR_POLLUTION_HISTORY_ROWS,
):
    """Build one bounded causal read for one exact measured series."""

    through = _aware(prediction_time, name="prediction_time")
    if type(lookback_minutes) is not int or lookback_minutes < 120:
        raise ValueError("lookback_minutes must be at least 120")
    if type(limit) is not int or not 1 <= limit <= MAX_AIR_POLLUTION_HISTORY_ROWS:
        raise ValueError(
            f"limit must be between 1 and {MAX_AIR_POLLUTION_HISTORY_ROWS}"
        )
    cell_id = air_pollution_series_cell_id(
        station_id, channel_id, pollutant, unit
    )
    point = cast(Observation.location, Geometry(geometry_type="POINT", srid=4326))
    return (
        select(
            Observation.id,
            Observation.source,
            Observation.cell_id,
            Observation.observed_at,
            Observation.ingested_at,
            Observation.payload,
            func.ST_Y(point).label("latitude"),
            func.ST_X(point).label("longitude"),
        )
        .where(
            Observation.source == AIR_POLLUTION_SOURCE,
            Observation.cell_id == cell_id,
            Observation.issued_at.is_(None),
            Observation.observed_at >= through - timedelta(minutes=lookback_minutes),
            Observation.observed_at <= through,
        )
        .order_by(Observation.observed_at.desc(), Observation.id.desc())
        .limit(limit)
    )


def read_air_pollution_series_history(
    *,
    station_id: str,
    channel_id: str,
    pollutant: str,
    unit: str,
    prediction_time: datetime,
    lookback_minutes: int = AIR_POLLUTION_TREND_LOOKBACK_MINUTES,
    limit: int = MAX_AIR_POLLUTION_HISTORY_ROWS,
) -> list[dict[str, Any]]:
    """Read an exact series causally and return it in chronological order."""

    statement = air_pollution_series_history_statement(
        station_id=station_id,
        channel_id=channel_id,
        pollutant=pollutant,
        unit=unit,
        prediction_time=prediction_time,
        lookback_minutes=lookback_minutes,
        limit=limit,
    )
    with Session() as session:
        newest_first = [
            dict(row) for row in session.execute(statement).mappings().all()
        ]
    return list(reversed(newest_first))


def _point(record: dict[str, Any]) -> WKTElement | None:
    latitude, longitude = record.get("latitude"), record.get("longitude")
    if latitude is None or longitude is None:
        return None
    return WKTElement(f"POINT({float(longitude)} {float(latitude)})", srid=4326)


def _row(source: str, record: dict[str, Any], ingested_at: datetime) -> dict[str, Any]:
    observed_at = record["observed_at"]
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must carry a UTC offset")
    return {
        "source": source,
        "cell_id": record["cell_id"],
        "location": _point(record),
        "observed_at": observed_at.astimezone(timezone.utc),
        "ingested_at": ingested_at,
        # Absent for every measured source, which is what makes it NULL and
        # what the identity constraint reads as "this was not predicted".
        "issued_at": record.get("issued_at"),
        "payload": record["payload"],
    }


def upsert_observations(source: str, records: Iterable[dict[str, Any]]) -> int:
    """Insert records, ignoring any that are already stored.

    Returns the number of rows actually written, so a collector run that
    re-fetched a window it already had reports 0 rather than claiming work.

    One ingested_at is stamped for the whole batch: it is the cursor clock, and
    a detector must not be able to observe half a collector run.
    """
    rows = list(records)
    if not rows:
        return 0

    ingested_at = datetime.now(timezone.utc)
    written = 0
    with Session() as session:
        for start in range(0, len(rows), CHUNK_SIZE):
            values = [_row(source, record, ingested_at) for record in rows[start:start + CHUNK_SIZE]]
            statement = (
                insert(Observation)
                .values(values)
                .on_conflict_do_nothing(constraint="observations_identity")
                .returning(Observation.id)
            )
            written += len(session.execute(statement).scalars().all())
        session.commit()
    return written


# Representative FWI value per GWIS/EFFIS danger band.
#
# The WMS exposes a categorised raster, not a number, so the collector stores a
# band and its range. A heatmap needs one scalar, and the band midpoint is the
# honest choice — the open-ended bands take their nearest bound plus a step
# rather than pretending to a precision the source never had.
FWI_BAND_VALUE = {
    "low": 6.0,
    "moderate": 16.0,
    "high": 30.0,
    "very_high": 44.0,
    "extreme": 60.0,
    "very_extreme": 80.0,
}


def latest_fire_danger_geojson() -> dict[str, Any]:
    """Return the most recent FWI reading per cell as GeoJSON points.

    FWI is a daily product, so "most recent" is one timestamp shared by every
    cell — no per-cell grouping needed.
    """
    with Session() as session:
        rows = session.execute(text("""
            SELECT cell_id,
                   ST_Y(location::geometry) AS latitude,
                   ST_X(location::geometry) AS longitude,
                   payload,
                   observed_at
            FROM observations
            WHERE source = 'fire_weather'
              AND observed_at = (
                  SELECT max(observed_at) FROM observations WHERE source = 'fire_weather'
              )
        """)).mappings().all()

    features = []
    for row in rows:
        level = (row["payload"] or {}).get("danger_level")
        value = FWI_BAND_VALUE.get(level)
        if value is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["longitude"], row["latitude"]],
            },
            "properties": {
                "cell_id": row["cell_id"],
                "danger_level": level,
                "fwi": value,
            },
        })

    return {
        "type": "FeatureCollection",
        "observed_at": rows[0]["observed_at"].isoformat() if rows else None,
        "features": features,
    }
