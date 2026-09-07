"""Writing raw observations. Nothing reads them yet — that is detection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from geoalchemy2 import WKTElement
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
