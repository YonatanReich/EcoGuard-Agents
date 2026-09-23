"""Flood-only writes to the normalized observation stream.

Water Authority collectors keep detailed provider tables and a normalized
copy for the flood detector. Both writes must commit together, so this module
accepts the collector's existing database session instead of changing the
shared observations repository used by other parts of the system.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from geoalchemy2 import WKTElement
from sqlalchemy.dialects.postgresql import insert

from ecoguard.database.models import Observation


CHUNK_SIZE = 500


def _point(record: dict[str, Any]) -> WKTElement | None:
    """A reading's position, or None when it has none."""
    latitude, longitude = record.get("latitude"), record.get("longitude")
    if latitude is None or longitude is None:
        return None
    return WKTElement(f"POINT({float(longitude)} {float(latitude)})", srid=4326)


def _row(
    source: str,
    record: dict[str, Any],
    ingested_at: datetime,
) -> dict[str, Any]:
    """One reading as a database row."""
    observed_at = record["observed_at"]
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must carry a UTC offset")
    return {
        "source": source,
        "cell_id": record["cell_id"],
        "location": _point(record),
        "observed_at": observed_at.astimezone(timezone.utc),
        "ingested_at": ingested_at,
        "issued_at": record.get("issued_at"),
        "payload": record["payload"],
    }


def upsert_flood_observations_in_session(
    session: Any,
    source: str,
    records: Iterable[dict[str, Any]],
    *,
    ingested_at: datetime,
) -> int:
    """Cache corrected flood signals inside the collector transaction."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be non-empty")
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise ValueError("ingested_at must carry a UTC offset")

    rows = list(records)
    written = 0
    stamped_at = ingested_at.astimezone(timezone.utc)
    for start in range(0, len(rows), CHUNK_SIZE):
        values = [
            _row(source, record, stamped_at)
            for record in rows[start : start + CHUNK_SIZE]
        ]
        statement = insert(Observation).values(values)
        statement = statement.on_conflict_do_update(
            constraint="observations_identity",
            set_={
                "payload": statement.excluded.payload,
                "location": statement.excluded.location,
                "ingested_at": statement.excluded.ingested_at,
            },
            where=Observation.payload.is_distinct_from(statement.excluded.payload),
        )
        written += len(
            session.execute(statement.returning(Observation.id)).scalars().all()
        )
    return written
