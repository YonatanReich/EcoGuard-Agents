"""Materialize slow, reusable flood-detector context in PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.collection.base import cell_for, service_area_cells


URBAN_BUILT_UP_FRACTION = 0.35
MIN_URBAN_SAMPLES = 5


UPSERT_CELLS = text(
    """
    INSERT INTO flood_cell_context (cell_id, location, refreshed_at)
    VALUES (
      :cell_id,
      ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
      :refreshed_at
    )
    ON CONFLICT (cell_id) DO UPDATE SET
      location = EXCLUDED.location,
      refreshed_at = EXCLUDED.refreshed_at
    """
)


ENRICH_CELLS = text(
    """
    UPDATE flood_cell_context AS context
    SET drainage_basin_id = enriched.drainage_basin_id,
        drainage_basin_source_id = enriched.drainage_basin_source_id,
        elevation_m = enriched.elevation_m,
        slope_deg = enriched.slope_deg,
        built_up_fraction = enriched.built_up_fraction,
        is_urban = enriched.is_urban,
        urban_classification_status = enriched.urban_classification_status,
        urban_sample_count = enriched.urban_sample_count,
        distance_to_stream_m = enriched.distance_to_stream_m,
        refreshed_at = :refreshed_at
    FROM (
      SELECT cell.cell_id,
             basin.id AS drainage_basin_id,
             basin.basin_id AS drainage_basin_source_id,
             surface.elevation_m,
             surface.slope_deg,
             urban.built_up_fraction,
             CASE
               WHEN urban.sample_count >= :minimum_urban_samples
                 THEN urban.built_up_fraction >= :urban_built_up_fraction
               ELSE NULL
             END AS is_urban,
             CASE
               WHEN urban.sample_count >= :minimum_urban_samples
                 THEN 'classified'
               ELSE 'unknown'
             END AS urban_classification_status,
             urban.sample_count AS urban_sample_count,
             stream.distance_m AS distance_to_stream_m
      FROM flood_cell_context AS cell
      LEFT JOIN LATERAL (
        SELECT candidate.id, candidate.basin_id
        FROM drainage_basins AS candidate
        WHERE ST_Covers(candidate.geometry, cell.location::geometry)
        ORDER BY ST_Area(candidate.geometry), candidate.basin_id
        LIMIT 1
      ) AS basin ON true
      LEFT JOIN LATERAL (
        SELECT candidate.elevation_m, candidate.slope_deg
        FROM surface_cells AS candidate
        WHERE ST_Covers(candidate.cell, cell.location::geometry)
        LIMIT 1
      ) AS surface ON true
      LEFT JOIN LATERAL (
        SELECT avg(sampled.built_up)::real AS built_up_fraction,
               count(sampled.built_up)::smallint AS sample_count
        FROM (
          SELECT surface_sample.built_up
          FROM (
            VALUES
              (0.0, 0.0),
              (-2000.0, -2000.0), (-2000.0, 0.0), (-2000.0, 2000.0),
              (0.0, -2000.0),                    (0.0, 2000.0),
              (2000.0, -2000.0),  (2000.0, 0.0), (2000.0, 2000.0)
          ) AS sample_offset(east_m, north_m)
          CROSS JOIN LATERAL (
            SELECT ST_Project(
                     ST_Project(
                       cell.location,
                       abs(sample_offset.north_m),
                       radians(CASE WHEN sample_offset.north_m >= 0 THEN 0 ELSE 180 END)
                     ),
                     abs(sample_offset.east_m),
                     radians(CASE WHEN sample_offset.east_m >= 0 THEN 90 ELSE 270 END)
                   )::geometry AS location
          ) AS sample_point
          LEFT JOIN LATERAL (
            SELECT candidate.built_up
            FROM surface_cells AS candidate
            WHERE ST_Covers(candidate.cell, sample_point.location)
            LIMIT 1
          ) AS surface_sample ON true
        ) AS sampled
      ) AS urban ON true
      LEFT JOIN LATERAL (
        SELECT ST_Distance(
                 cell.location,
                 candidate.geometry::geography
               )::real AS distance_m
        FROM streams AS candidate
        ORDER BY ST_Distance(cell.location, candidate.geometry::geography)
        LIMIT 1
      ) AS stream ON true
    ) AS enriched
    WHERE context.cell_id = enriched.cell_id
    """
)


REBUILD_BASELINES = text(
    """
    WITH baseline_input AS (
      SELECT observation.hydrometric_station_id,
             observation.observed_at,
             observation.discharge_m3s,
             observation.water_height_m
      FROM hydrometric_observations AS observation
      WHERE observation.hydrometric_station_id IS NOT NULL
        AND observation.observed_at < :computed_at - interval '7 days'
      UNION ALL
      SELECT station_link.hydrometric_station_id,
             observation.observed_at,
             observation.discharge_m3s,
             NULL::double precision AS water_height_m
      FROM historical_hydrometric_observations AS observation
      JOIN hydrometric_station_history_links AS station_link
        ON station_link.historical_station_id =
           observation.historical_station_id
      WHERE NOT observation.is_sewage
    ),
    historical AS (
      -- Segment boundaries repeat some source timestamps. Collapse them once
      -- before calculating counts and percentiles. MAX keeps a non-null value
      -- and avoids lowering the fallback threshold on a conflicting boundary.
      -- Historical water elevation is cached for audit but excluded here
      -- because its datum has not been proven equivalent to the live height.
      SELECT observation.hydrometric_station_id,
             observation.observed_at,
             max(observation.discharge_m3s) AS discharge_m3s,
             max(observation.water_height_m) AS water_height_m
      FROM baseline_input AS observation
      GROUP BY observation.hydrometric_station_id, observation.observed_at
    ),
    station_coverage AS (
      SELECT observation.hydrometric_station_id,
             count(DISTINCT EXTRACT(MONTH FROM observation.observed_at))::smallint
               AS covered_months,
             floor(
               EXTRACT(EPOCH FROM (
                 max(observation.observed_at) - min(observation.observed_at)
               )) / 86400
             )::integer AS history_span_days
      FROM historical AS observation
      GROUP BY observation.hydrometric_station_id
    )
    INSERT INTO flood_station_baselines (
      hydrometric_station_id, month,
      discharge_sample_count, discharge_distinct_days,
      stage_sample_count, stage_distinct_days,
      covered_months, history_span_days,
      discharge_median_m3s, discharge_p95_m3s,
      stage_median_m, stage_p95_m, computed_at
    )
    SELECT observation.hydrometric_station_id,
           EXTRACT(MONTH FROM observation.observed_at)::smallint,
           count(observation.discharge_m3s)::integer,
           (count(DISTINCT observation.observed_at::date)
             FILTER (WHERE observation.discharge_m3s IS NOT NULL))::integer,
           count(observation.water_height_m)::integer,
           (count(DISTINCT observation.observed_at::date)
             FILTER (WHERE observation.water_height_m IS NOT NULL))::integer,
           coverage.covered_months,
           coverage.history_span_days,
           percentile_cont(0.50) WITHIN GROUP (
             ORDER BY observation.discharge_m3s
           ) FILTER (WHERE observation.discharge_m3s IS NOT NULL),
           percentile_cont(0.95) WITHIN GROUP (
             ORDER BY observation.discharge_m3s
           ) FILTER (WHERE observation.discharge_m3s IS NOT NULL),
           percentile_cont(0.50) WITHIN GROUP (
             ORDER BY observation.water_height_m
           ) FILTER (WHERE observation.water_height_m IS NOT NULL),
           percentile_cont(0.95) WITHIN GROUP (
             ORDER BY observation.water_height_m
           ) FILTER (WHERE observation.water_height_m IS NOT NULL),
           :computed_at
    FROM historical AS observation
    JOIN station_coverage AS coverage
      ON coverage.hydrometric_station_id = observation.hydrometric_station_id
    WHERE coverage.covered_months = 12
      AND coverage.history_span_days >= 330
    GROUP BY observation.hydrometric_station_id,
             EXTRACT(MONTH FROM observation.observed_at),
             coverage.covered_months,
             coverage.history_span_days
    HAVING (
      count(observation.discharge_m3s) >= 300 AND
      count(DISTINCT observation.observed_at::date)
        FILTER (WHERE observation.discharge_m3s IS NOT NULL) >= 10
    ) OR (
      count(observation.water_height_m) >= 300 AND
      count(DISTINCT observation.observed_at::date)
        FILTER (WHERE observation.water_height_m IS NOT NULL) >= 10
    )
    """
)


def _station_context_rows(session: Any, table: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            SELECT station.id,
                   ST_Y(station.location::geometry) AS latitude,
                   ST_X(station.location::geometry) AS longitude,
                   basin.id AS drainage_basin_id
            FROM {table} AS station
            LEFT JOIN LATERAL (
              SELECT candidate.id
              FROM drainage_basins AS candidate
              WHERE ST_Covers(candidate.geometry, station.location::geometry)
              ORDER BY ST_Area(candidate.geometry), candidate.basin_id
              LIMIT 1
            ) AS basin ON true
            """
        )
    ).mappings()
    return [
        {
            "id": row["id"],
            "cell_id": cell_for(row["latitude"], row["longitude"]),
            "drainage_basin_id": row["drainage_basin_id"],
        }
        for row in rows
    ]


def rebuild_flood_station_baselines_in_session(
    session: Any,
    *,
    computed_at: datetime,
) -> int:
    """Replace compact baseline rows inside the caller's transaction."""
    session.execute(text("DELETE FROM flood_station_baselines"))
    baseline_count = session.execute(
        REBUILD_BASELINES,
        {"computed_at": computed_at},
    ).rowcount
    return max(baseline_count or 0, 0)


def refresh_flood_station_baselines() -> int:
    """Rebuild monthly baselines without repeating spatial materialization."""
    from ecoguard.database.engine import Session

    with Session() as session:
        baseline_count = rebuild_flood_station_baselines_in_session(
            session,
            computed_at=datetime.now(timezone.utc),
        )
        session.commit()
    return baseline_count


def refresh_flood_static_context() -> dict[str, int]:
    """Refresh grid enrichment, station-to-cell links and monthly baselines.

    Run this after the hydrology and surface static loaders. It is deliberately
    explicit rather than part of the real-time worker because all spatial joins
    and percentile calculations are stable between source-data refreshes.
    """
    from ecoguard.database.engine import Session

    refreshed_at = datetime.now(timezone.utc)
    cell_rows = [
        {
            "cell_id": cell.cell_id,
            "latitude": cell.latitude,
            "longitude": cell.longitude,
            "refreshed_at": refreshed_at,
        }
        for cell in service_area_cells()
    ]

    with Session() as session:
        session.execute(UPSERT_CELLS, cell_rows)
        session.execute(
            ENRICH_CELLS,
            {
                "refreshed_at": refreshed_at,
                "minimum_urban_samples": MIN_URBAN_SAMPLES,
                "urban_built_up_fraction": URBAN_BUILT_UP_FRACTION,
            },
        )

        hydrometric_rows = _station_context_rows(session, "hydrometric_stations")
        rain_rows = _station_context_rows(session, "rain_stations")
        if hydrometric_rows:
            session.execute(
                text(
                    "UPDATE hydrometric_stations "
                    "SET cell_id = :cell_id, drainage_basin_id = :drainage_basin_id "
                    "WHERE id = :id"
                ),
                hydrometric_rows,
            )
        if rain_rows:
            session.execute(
                text(
                    "UPDATE rain_stations "
                    "SET cell_id = :cell_id, drainage_basin_id = :drainage_basin_id "
                    "WHERE id = :id"
                ),
                rain_rows,
            )

        baseline_count = rebuild_flood_station_baselines_in_session(
            session,
            computed_at=refreshed_at,
        )
        session.commit()

    return {
        "cells": len(cell_rows),
        "hydrometric_stations": len(hydrometric_rows),
        "rain_stations": len(rain_rows),
        "baselines": max(baseline_count or 0, 0),
    }
