"""Writing raw observations. Nothing reads them yet — that is detection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from ecoguard.database.engine import Session
from ecoguard.database.models import Observation

# One statement per chunk. A national weather sweep is ~1,200 rows, which is
# comfortable in a single INSERT, but FIRMS after a bad fire day is not.
CHUNK_SIZE = 500


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
