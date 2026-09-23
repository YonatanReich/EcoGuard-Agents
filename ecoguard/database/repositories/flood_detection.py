"""Read-only persistence boundary for hydrometric flood detection."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import bindparam, text

from ecoguard.database.engine import Session


WINDOW_OBSERVATIONS = text(
    """
    SELECT id, source, cell_id, observed_at, ingested_at, payload,
           ST_Y(location::geometry) AS latitude,
           ST_X(location::geometry) AS longitude
    FROM observations
    WHERE source = :source
      AND cell_id IN :cell_ids
      AND observed_at >= :observed_since
      AND observed_at <= :observed_through
    ORDER BY cell_id, observed_at, id
    """
).bindparams(bindparam("cell_ids", expanding=True))


STATION_STREAM_IDS = text(
    """
    SELECT station.source_station_id,
           (topology.stream_context -> 'stream' ->> 'stream_id')::bigint
             AS stream_id
    FROM hydrometric_stations AS station
    JOIN flood_station_topology AS topology
      ON topology.hydrometric_station_id = station.id
    WHERE station.source_station_id IN :station_ids
      AND station.flow_threshold_status = 'complete_thresholds'
      AND topology.stream_context @> '{"matched": true}'::jsonb
      AND topology.stream_context -> 'stream' ->> 'stream_id' IS NOT NULL
    """
).bindparams(bindparam("station_ids", expanding=True))


def load_window(
    cell_ids: Sequence[str],
    source: str,
    *,
    observed_since: datetime,
    observed_through: datetime,
) -> list[dict[str, Any]]:
    """The readings a flood detector needs for one run."""
    if not cell_ids:
        return []
    with Session() as session:
        return [
            dict(row)
            for row in session.execute(
                WINDOW_OBSERVATIONS,
                {
                    "cell_ids": list(cell_ids),
                    "source": source,
                    "observed_since": observed_since,
                    "observed_through": observed_through,
                },
            ).mappings()
        ]


def load_stream_ids(source_station_ids: Sequence[int]) -> dict[int, int]:
    """Load only confirmed station-to-stream matches for output enrichment."""
    if not source_station_ids:
        return {}
    with Session() as session:
        rows = session.execute(
            STATION_STREAM_IDS,
            {"station_ids": list(source_station_ids)},
        ).mappings()
        return {
            int(row["source_station_id"]): int(row["stream_id"])
            for row in rows
        }
