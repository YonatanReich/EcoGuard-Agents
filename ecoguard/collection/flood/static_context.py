"""Materialize slow, reusable flood-detector context in PostgreSQL."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.collection.base import cell_for, service_area_cells
from ecoguard.detectors.flood.topology import (
    build_downstream_route,
    build_stream_context,
)


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


STATION_TOPOLOGY_INPUT = text(
    """
    SELECT station.id AS hydrometric_station_id,
           station.source_station_id,
           station.name_he AS station_name_he,
           station.name_en AS station_name_en,
           ST_Y(station.location::geometry) AS latitude,
           ST_X(station.location::geometry) AS longitude,
           basin.basin_id,
           COALESCE(stream_match.candidates, '[]'::jsonb) AS stream_candidates
    FROM hydrometric_stations AS station
    LEFT JOIN drainage_basins AS basin
      ON basin.id = station.drainage_basin_id
    LEFT JOIN LATERAL (
      SELECT jsonb_agg(
        jsonb_build_object(
          'stream_id', candidate.stream_id,
          'object_id', candidate.object_id,
          'name_he', candidate.name_he,
          'water_source_id', candidate.water_source_id,
          'main_catchment_code', candidate.main_catchment_code,
          'main_catchment_name', candidate.main_catchment_name,
          'draining_water_id', candidate.draining_water_id,
          'draining_water_name', candidate.draining_water_name,
          'distance_m', candidate.distance_m
        )
        ORDER BY candidate.distance_m, candidate.object_id
      ) AS candidates
      FROM (
        SELECT stream.id AS stream_id,
               stream.object_id,
               stream.name_he,
               stream.water_source_id,
               stream.main_catchment_code,
               stream.main_catchment_name,
               stream.draining_water_id,
               stream.draining_water_name,
               ST_Distance(
                 station.location,
                 stream.geometry::geography
               ) AS distance_m
        FROM streams AS stream
        WHERE basin.id IS NOT NULL
          AND ST_Intersects(stream.geometry, basin.geometry)
          AND ST_DWithin(
            station.location,
            stream.geometry::geography,
            2000.0
          )
        ORDER BY
          ST_Distance(station.location, stream.geometry::geography),
          stream.object_id
        LIMIT 20
      ) AS candidate
    ) AS stream_match ON true
    WHERE station.flow_threshold_status = 'complete_thresholds'
    ORDER BY station.source_station_id
    """
)


STREAM_NETWORK_INPUT = text(
    """
    SELECT node.water_source_id,
           node.name_he,
           node.object_ids,
           node.feature_count,
           node.main_catchment_code,
           node.main_catchment_name,
           edge.downstream_water_source_id AS draining_water_id,
           edge.downstream_water_name AS draining_water_name,
           ST_Y(node.representative_location) AS representative_latitude,
           ST_X(node.representative_location) AS representative_longitude,
           node.topology_conflict
    FROM stream_network_nodes AS node
    LEFT JOIN stream_network_edges AS edge
      ON edge.upstream_water_source_id = node.water_source_id
     AND NOT node.topology_conflict
    ORDER BY node.water_source_id
    """
)


def _station_context_rows(session: Any, table: str) -> list[dict[str, Any]]:
    eligibility_filter = (
        "WHERE station.flow_threshold_status = 'complete_thresholds'"
        if table == "hydrometric_stations"
        else ""
    )
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
            {eligibility_filter}
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


def rebuild_flood_station_topology_in_session(
    session: Any,
    *,
    refreshed_at: datetime,
) -> int:
    """Materialize stable gauge-to-stream matches and their full routes."""
    network: dict[int, dict[str, Any]] = {}
    for result in session.execute(STREAM_NETWORK_INPUT).mappings():
        row = dict(result)
        latitude = row.pop("representative_latitude", None)
        longitude = row.pop("representative_longitude", None)
        row["representative_location"] = (
            {"latitude": latitude, "longitude": longitude}
            if latitude is not None and longitude is not None
            else None
        )
        network[int(row["water_source_id"])] = row

    rows = []
    for result in session.execute(STATION_TOPOLOGY_INPUT).mappings():
        station = dict(result)
        candidates = station.pop("stream_candidates", None) or []
        stream_context = build_stream_context(station, candidates)
        rows.append(
            {
                "hydrometric_station_id": station["hydrometric_station_id"],
                "stream_context": json.dumps(
                    stream_context, ensure_ascii=False, sort_keys=True
                ),
                "downstream_route": json.dumps(
                    build_downstream_route(stream_context, network),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "refreshed_at": refreshed_at,
            }
        )

    session.execute(text("DELETE FROM flood_station_topology"))
    if rows:
        session.execute(
            text(
                """
                INSERT INTO flood_station_topology (
                  hydrometric_station_id, stream_context,
                  downstream_route, refreshed_at
                ) VALUES (
                  :hydrometric_station_id,
                  CAST(:stream_context AS jsonb),
                  CAST(:downstream_route AS jsonb),
                  :refreshed_at
                )
                """
            ),
            rows,
        )
    return len(rows)


def refresh_flood_station_topology() -> int:
    """Refresh only the static station-to-stream routes already stored in DB."""
    from ecoguard.database.engine import Session

    with Session() as session:
        station_count = rebuild_flood_station_topology_in_session(
            session,
            refreshed_at=datetime.now(timezone.utc),
        )
        session.commit()
    return station_count


def refresh_flood_static_context() -> dict[str, int]:
    """Refresh grid enrichment, station-to-cell links and stream topology.

    Run this after the hydrology and surface static loaders. It is deliberately
    explicit rather than part of the real-time worker because the spatial joins
    and stream matching are stable between source-data refreshes.
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

        station_topology_count = rebuild_flood_station_topology_in_session(
            session,
            refreshed_at=refreshed_at,
        )

        # Basin assignments can change when either station catalog or basin
        # geometry is refreshed. Rebuild the derived IDF links in the same
        # transaction so consumers never see mismatched basin relationships.
        from ecoguard.collection.flood.rainfall_idf import (
            refresh_hydrometric_idf_basin_links_in_session,
        )

        hydrometric_idf_link_count = refresh_hydrometric_idf_basin_links_in_session(
            session, linked_at=refreshed_at
        )

        session.commit()

    return {
        "cells": len(cell_rows),
        "hydrometric_stations": len(hydrometric_rows),
        "rain_stations": len(rain_rows),
        "station_topologies": station_topology_count,
        "hydrometric_idf_links": hydrometric_idf_link_count,
    }
