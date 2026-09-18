"""Database boundary for the cursor-based flood worker."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import bindparam, text

from ecoguard.database.engine import Session


DETECTOR_NAME = "flood"
DEFAULT_BATCH_SIZE = 1000


@dataclass(frozen=True)
class CursorPosition:
    source: str
    ingested_at: datetime
    observation_id: int


@dataclass(frozen=True)
class PendingBatch:
    observations: list[dict[str, Any]]
    high_watermarks: list[CursorPosition]


@dataclass(frozen=True)
class CommitResult:
    inserted_candidate_keys: set[str]
    resolved_event_keys: set[str]


PENDING_OBSERVATIONS = text(
    """
    SELECT id, source, cell_id, observed_at, ingested_at, payload,
           ST_Y(location::geometry) AS latitude,
           ST_X(location::geometry) AS longitude
    FROM observations
    WHERE source = :source
      AND (
        CAST(:last_ingested_at AS timestamptz) IS NULL
        OR ingested_at > CAST(:last_ingested_at AS timestamptz)
        OR (
          ingested_at = CAST(:last_ingested_at AS timestamptz)
          AND id > CAST(:last_observation_id AS bigint)
        )
      )
    ORDER BY ingested_at, id
    LIMIT :limit
    """
)


WINDOW_OBSERVATIONS = text(
    """
    SELECT id, source, cell_id, observed_at, ingested_at, payload,
           ST_Y(location::geometry) AS latitude,
           ST_X(location::geometry) AS longitude
    FROM observations
    WHERE source IN :sources
      AND cell_id IN :cell_ids
      AND observed_at >= :observed_since
      AND observed_at <= :observed_through
    ORDER BY cell_id, observed_at, source, id
    """
).bindparams(bindparam("sources", expanding=True), bindparam("cell_ids", expanding=True))


BASIN_RAIN_OBSERVATIONS = text(
    """
    WITH basin_cells AS (
      SELECT drainage_basin_id, count(*)::integer AS cell_count
      FROM flood_cell_context
      WHERE drainage_basin_id IN :basin_ids
      GROUP BY drainage_basin_id
    )
    SELECT observation.id, observation.source, observation.cell_id,
           observation.observed_at, observation.ingested_at,
           observation.payload, context.drainage_basin_id,
           basin_cells.cell_count AS spatial_cell_count,
           ST_Y(observation.location::geometry) AS latitude,
           ST_X(observation.location::geometry) AS longitude
    FROM observations AS observation
    JOIN flood_cell_context AS context
      ON context.cell_id = observation.cell_id
    JOIN basin_cells
      ON basin_cells.drainage_basin_id = context.drainage_basin_id
    WHERE observation.source IN :sources
      AND context.drainage_basin_id IN :basin_ids
      AND observation.observed_at >= :observed_since
      AND observation.observed_at <= :observed_through
    ORDER BY context.drainage_basin_id, observation.observed_at,
             observation.cell_id, observation.source, observation.id
    """
).bindparams(
    bindparam("sources", expanding=True),
    bindparam("basin_ids", expanding=True),
)


CELL_CONTEXT = text(
    """
    SELECT context.cell_id,
           ST_Y(context.location::geometry) AS latitude,
           ST_X(context.location::geometry) AS longitude,
           context.drainage_basin_id,
           context.drainage_basin_source_id,
           basin.name_he AS drainage_basin_name_he,
           basin.name_en AS drainage_basin_name_en,
           context.elevation_m,
           context.slope_deg,
           context.built_up_fraction,
           context.is_urban,
           context.urban_classification_status,
           context.urban_sample_count,
           context.distance_to_stream_m
    FROM flood_cell_context AS context
    LEFT JOIN drainage_basins AS basin
      ON basin.id = context.drainage_basin_id
    WHERE context.cell_id IN :cell_ids
    """
).bindparams(bindparam("cell_ids", expanding=True))


STATION_CONTEXTS = text(
    """
    SELECT station.source_station_id,
           station.id AS hydrometric_station_id,
           station.name_he,
           station.name_en,
           ST_Y(station.location::geometry) AS latitude,
           ST_X(station.location::geometry) AS longitude,
           basin.basin_id,
           basin.name_he AS basin_name_he,
           basin.name_en AS basin_name_en,
           topology.stream_context,
           topology.downstream_route,
           topology.refreshed_at AS topology_refreshed_at
    FROM hydrometric_stations AS station
    LEFT JOIN drainage_basins AS basin
      ON basin.id = station.drainage_basin_id
    LEFT JOIN flood_station_topology AS topology
      ON topology.hydrometric_station_id = station.id
    WHERE station.source_station_id IN :station_ids
      AND station.flow_threshold_status = 'complete_thresholds'
    """
).bindparams(bindparam("station_ids", expanding=True))


ACTIVE_EVENTS = text(
    """
    SELECT event_key, candidate_key, cell_id, observed_at AS opened_at,
           trigger, evidence
    FROM flood_candidates
    WHERE status = 'active'
      AND cell_id IN :cell_ids
    ORDER BY cell_id, observed_at, id
    """
).bindparams(bindparam("cell_ids", expanding=True))


class FloodWorkerRepository:
    """Keep all detector state changes behind one small repository API."""

    def load_pending(
        self, sources: Sequence[str], *, limit_per_source: int = DEFAULT_BATCH_SIZE
    ) -> PendingBatch:
        if limit_per_source < 1:
            raise ValueError("limit_per_source must be positive")
        observations: list[dict[str, Any]] = []
        high_watermarks: list[CursorPosition] = []
        with Session() as session:
            cursors = {
                row["source"]: row
                for row in session.execute(
                    text(
                        """
                        SELECT source, last_ingested_at, last_observation_id
                        FROM detector_cursors
                        WHERE detector_name = :detector_name
                        """
                    ),
                    {"detector_name": DETECTOR_NAME},
                ).mappings()
            }
            for source in sources:
                cursor = cursors.get(source)
                rows = [
                    dict(row)
                    for row in session.execute(
                        PENDING_OBSERVATIONS,
                        {
                            "source": source,
                            "last_ingested_at": (
                                cursor["last_ingested_at"] if cursor else None
                            ),
                            "last_observation_id": (
                                cursor["last_observation_id"] if cursor else 0
                            ),
                            "limit": limit_per_source,
                        },
                    ).mappings()
                ]
                observations.extend(rows)
                if rows:
                    last = rows[-1]
                    high_watermarks.append(
                        CursorPosition(
                            source=source,
                            ingested_at=last["ingested_at"],
                            observation_id=last["id"],
                        )
                    )
        return PendingBatch(observations, high_watermarks)

    def load_window(
        self,
        cell_ids: Sequence[str],
        sources: Sequence[str],
        *,
        observed_since: datetime,
        observed_through: datetime,
    ) -> list[dict[str, Any]]:
        if not cell_ids:
            return []
        with Session() as session:
            return [
                dict(row)
                for row in session.execute(
                    WINDOW_OBSERVATIONS,
                    {
                        "cell_ids": list(cell_ids),
                        "sources": list(sources),
                        "observed_since": observed_since,
                        "observed_through": observed_through,
                    },
                ).mappings()
            ]

    def load_context(self, cell_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not cell_ids:
            return {}
        with Session() as session:
            return {
                row["cell_id"]: dict(row)
                for row in session.execute(
                    CELL_CONTEXT, {"cell_ids": list(cell_ids)}
                ).mappings()
            }

    def load_basin_rain_window(
        self,
        basin_ids: Sequence[int],
        sources: Sequence[str],
        *,
        observed_since: datetime,
        observed_through: datetime,
    ) -> list[dict[str, Any]]:
        """Load area-normalized rain inputs for the affected drainage basins."""
        if not basin_ids:
            return []
        with Session() as session:
            return [
                dict(row)
                for row in session.execute(
                    BASIN_RAIN_OBSERVATIONS,
                    {
                        "basin_ids": list(basin_ids),
                        "sources": list(sources),
                        "observed_since": observed_since,
                        "observed_through": observed_through,
                    },
                ).mappings()
            ]

    def load_station_contexts(
        self, source_station_ids: Sequence[int]
    ) -> dict[int, dict[str, Any]]:
        """Load materialized station, basin and downstream-route context."""
        if not source_station_ids:
            return {}
        with Session() as session:
            rows = session.execute(
                STATION_CONTEXTS,
                {"station_ids": list(source_station_ids)},
            ).mappings()
            return {
                int(row["source_station_id"]): dict(row)
                for row in rows
            }

    def load_active_events(
        self, cell_ids: Sequence[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Return only open events in the cells touched by this run."""
        events: dict[str, list[dict[str, Any]]] = {}
        if not cell_ids:
            return events
        with Session() as session:
            rows = session.execute(
                ACTIVE_EVENTS, {"cell_ids": list(cell_ids)}
            ).mappings()
            for row in rows:
                event = dict(row)
                events.setdefault(event["cell_id"], []).append(event)
        return events

    def commit_success(
        self,
        candidates: Iterable[Any],
        resolutions: Iterable[Any],
        high_watermarks: Sequence[CursorPosition],
    ) -> CommitResult:
        """Persist lifecycle transitions and consumed cursors atomically."""
        candidate_rows = [
            {
                "event_key": candidate.event_key,
                "candidate_key": candidate.candidate_key,
                "cell_id": candidate.cell_id,
                "observed_at": candidate.observed_at,
                "latitude": candidate.latitude,
                "longitude": candidate.longitude,
                "confidence": candidate.confidence,
                "severity_hint": candidate.severity_hint,
                "location_uncertainty_m": candidate.location_uncertainty_m,
                "trigger": candidate.trigger,
                "evidence": json.dumps(
                    candidate.database_evidence(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "emitted_at": datetime.now(timezone.utc),
            }
            for candidate in candidates
        ]
        resolution_rows = [
            {
                "event_key": resolution.event_key,
                "resolved_at": resolution.observed_at,
                "resolution_reason": resolution.reason,
                "resolution_evidence": json.dumps(
                    resolution.evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
            for resolution in resolutions
        ]
        inserted: set[str] = set()
        resolved: set[str] = set()
        with Session() as session:
            # Resolve first so a later crossing in the same atomic batch can
            # open a new row for the same stable event key.
            for row in resolution_rows:
                event_key = session.execute(
                    text(
                        """
                        UPDATE flood_candidates
                        SET status = 'resolved',
                            resolved_at = :resolved_at,
                            resolution_reason = :resolution_reason,
                            resolution_evidence = CAST(:resolution_evidence AS jsonb)
                        WHERE event_key = :event_key
                          AND status = 'active'
                        RETURNING event_key
                        """
                    ),
                    row,
                ).scalar_one_or_none()
                if event_key is not None:
                    resolved.add(event_key)

            if candidate_rows:
                inserted.update(
                    session.execute(
                        text(
                            """
                            INSERT INTO flood_candidates (
                              event_key, candidate_key, cell_id, observed_at, location,
                              confidence, severity_hint, location_uncertainty_m,
                              trigger, evidence, emitted_at
                            ) VALUES (
                              :event_key, :candidate_key, :cell_id, :observed_at,
                              ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                              :confidence, :severity_hint, :location_uncertainty_m,
                              :trigger, CAST(:evidence AS jsonb), :emitted_at
                            )
                            ON CONFLICT DO NOTHING
                            RETURNING candidate_key
                            """
                        ),
                        candidate_rows,
                    ).scalars()
                )

            updated_at = datetime.now(timezone.utc)
            cursor_rows = [
                {
                    "detector_name": DETECTOR_NAME,
                    "source": cursor.source,
                    "last_ingested_at": cursor.ingested_at,
                    "last_observation_id": cursor.observation_id,
                    "updated_at": updated_at,
                }
                for cursor in high_watermarks
            ]
            if cursor_rows:
                session.execute(
                    text(
                        """
                        INSERT INTO detector_cursors (
                          detector_name, source, last_ingested_at,
                          last_observation_id, updated_at
                        ) VALUES (
                          :detector_name, :source, :last_ingested_at,
                          :last_observation_id, :updated_at
                        )
                        ON CONFLICT (detector_name, source) DO UPDATE SET
                          last_ingested_at = EXCLUDED.last_ingested_at,
                          last_observation_id = EXCLUDED.last_observation_id,
                          updated_at = EXCLUDED.updated_at
                        WHERE (detector_cursors.last_ingested_at,
                               detector_cursors.last_observation_id)
                              < (EXCLUDED.last_ingested_at,
                                 EXCLUDED.last_observation_id)
                        """
                    ),
                    cursor_rows,
                )
            session.commit()
        return CommitResult(inserted, resolved)
