"""Read cached station histories consumed by flood detection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text


HYDROMETRIC_STATION_HISTORIES = text(
    """
    WITH latest_observation AS (
      SELECT DISTINCT ON (observation.source_station_id)
        observation.source_station_id,
        observation.observed_at,
        observation.discharge_m3s,
        observation.water_height_m
      FROM hydrometric_observations AS observation
      ORDER BY
        observation.source_station_id,
        observation.observed_at DESC,
        observation.id DESC
    )
    SELECT
      latest.source_station_id,
      latest.observed_at,
      latest.discharge_m3s,
      latest.water_height_m,
      station.id AS hydrometric_station_id,
      station.name_he AS station_name_he,
      station.name_en AS station_name_en,
      ST_Y(station.location::geometry) AS latitude,
      ST_X(station.location::geometry) AS longitude,
      station.flow_start_water_level_m,
      station.flow_threshold_2y_m3s,
      station.flow_threshold_5y_m3s,
      station.flow_threshold_10y_m3s,
      station.flow_threshold_20y_m3s,
      station.flow_threshold_50y_m3s,
      station.flow_threshold_100y_m3s,
      basin.basin_id,
      basin.basin_name_he,
      basin.basin_name_en,
      history.observed_at AS history_observed_at,
      history.discharge_m3s AS history_discharge_m3s,
      history.water_height_m AS history_water_height_m,
      COALESCE(rainfall.evidence, '[]'::jsonb) AS rainfall_evidence,
      COALESCE(stream_match.candidates, '[]'::jsonb) AS stream_candidates
    FROM latest_observation AS latest
    LEFT JOIN hydrometric_stations AS station
      ON station.source_station_id = latest.source_station_id
    LEFT JOIN LATERAL (
      SELECT
        candidate.basin_id,
        candidate.name_he AS basin_name_he,
        candidate.name_en AS basin_name_en,
        candidate.geometry AS basin_geometry
      FROM drainage_basins AS candidate
      WHERE station.location IS NOT NULL
        AND ST_Covers(candidate.geometry, station.location::geometry)
      ORDER BY ST_Area(candidate.geometry) ASC, candidate.basin_id ASC
      LIMIT 1
    ) AS basin ON true
    LEFT JOIN LATERAL (
      SELECT
        array_agg(
          observation.observed_at ORDER BY observation.observed_at
        ) AS observed_at,
        array_agg(
          observation.discharge_m3s ORDER BY observation.observed_at
        ) AS discharge_m3s,
        array_agg(
          observation.water_height_m ORDER BY observation.observed_at
        ) AS water_height_m
      FROM hydrometric_observations AS observation
      WHERE observation.source_station_id = latest.source_station_id
        AND observation.observed_at >= :observed_since
    ) AS history ON true
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
        SELECT
          stream.id AS stream_id,
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
        WHERE station.location IS NOT NULL
          AND basin.basin_geometry IS NOT NULL
          AND ST_Intersects(stream.geometry, basin.basin_geometry)
          AND ST_DWithin(
            station.location,
            stream.geometry::geography,
            :stream_candidate_radius_m
          )
        ORDER BY
          ST_Distance(station.location, stream.geometry::geography),
          stream.object_id
        LIMIT :stream_candidate_limit
      ) AS candidate
    ) AS stream_match ON true
    LEFT JOIN LATERAL (
      SELECT jsonb_agg(
        jsonb_build_object(
          'source_station_id', rain_station.source_station_id,
          'name_he', rain_station.name_he,
          'name_en', rain_station.name_en,
          'latitude', ST_Y(rain_station.location::geometry),
          'longitude', ST_X(rain_station.location::geometry),
          'latest_observed_at', metrics.latest_observed_at,
          'rainfall_10m_mm', metrics.rainfall_10m_mm,
          'rainfall_1h_mm', metrics.rainfall_1h_mm,
          'rainfall_6h_mm', metrics.rainfall_6h_mm,
          'rainfall_24h_mm', metrics.rainfall_24h_mm
        )
        ORDER BY rain_station.source_station_id
      ) AS evidence
      FROM rain_stations AS rain_station
      LEFT JOIN LATERAL (
        SELECT
          latest.latest_observed_at,
          totals.rainfall_10m_mm,
          totals.rainfall_1h_mm,
          totals.rainfall_6h_mm,
          totals.rainfall_24h_mm
        FROM (
          SELECT max(observation.observed_at) AS latest_observed_at
          FROM rainfall_observations AS observation
          WHERE observation.source_station_id =
                rain_station.source_station_id
            AND observation.observed_at >= :rainfall_since
            AND observation.observed_at <= :as_of
        ) AS latest
        LEFT JOIN LATERAL (
          SELECT
            sum(observation.rainfall_mm) FILTER (
              WHERE observation.observed_at >
                    latest.latest_observed_at - interval '10 minutes'
            ) AS rainfall_10m_mm,
            sum(observation.rainfall_mm) FILTER (
              WHERE observation.observed_at >
                    latest.latest_observed_at - interval '1 hour'
            ) AS rainfall_1h_mm,
            sum(observation.rainfall_mm) FILTER (
              WHERE observation.observed_at >
                    latest.latest_observed_at - interval '6 hours'
            ) AS rainfall_6h_mm,
            sum(observation.rainfall_mm) FILTER (
              WHERE observation.observed_at >
                    latest.latest_observed_at - interval '24 hours'
            ) AS rainfall_24h_mm
          FROM rainfall_observations AS observation
          WHERE observation.source_station_id =
                rain_station.source_station_id
            AND observation.observed_at >= :rainfall_since
            AND observation.observed_at <= latest.latest_observed_at
        ) AS totals ON true
      ) AS metrics ON true
      WHERE rain_station.is_active
        AND basin.basin_geometry IS NOT NULL
        AND ST_Covers(
          basin.basin_geometry,
          rain_station.location::geometry
        )
    ) AS rainfall ON true
    ORDER BY latest.source_station_id
    """
)


STREAM_NETWORK = text(
    """
    SELECT
      stream.id AS stream_id,
      stream.object_id,
      stream.name_he,
      stream.water_source_id,
      stream.main_catchment_code,
      stream.main_catchment_name,
      stream.draining_water_id,
      stream.draining_water_name,
      ST_Y(ST_PointOnSurface(stream.geometry)) AS representative_latitude,
      ST_X(ST_PointOnSurface(stream.geometry)) AS representative_longitude
    FROM streams AS stream
    ORDER BY
      stream.water_source_id NULLS LAST,
      stream.object_id
    """
)


LATEST_COLLECTOR_RUNS = text(
    """
    SELECT DISTINCT ON (run.source)
      run.source,
      run.started_at,
      run.finished_at,
      run.status,
      run.rows_written,
      run.error
    FROM collector_runs AS run
    WHERE run.source IN :sources
    ORDER BY run.source, run.started_at DESC, run.id DESC
    """
).bindparams(bindparam("sources", expanding=True))


class PostgresFloodDetectionRepository:
    """Load recent histories without dropping unknown provider stations."""

    def load_station_histories(
        self,
        *,
        observed_since: datetime,
        rainfall_since: datetime,
        as_of: datetime,
        stream_candidate_radius_m: float,
        stream_candidate_limit: int,
    ) -> list[dict[str, Any]]:
        # Import lazily so pure detector tests do not require a configured DB.
        from ecoguard.database.engine import Session

        with Session() as session:
            rows = session.execute(
                HYDROMETRIC_STATION_HISTORIES,
                {
                    "observed_since": observed_since,
                    "rainfall_since": rainfall_since,
                    "as_of": as_of,
                    "stream_candidate_radius_m": stream_candidate_radius_m,
                    "stream_candidate_limit": stream_candidate_limit,
                },
            ).mappings().all()

        histories: list[dict[str, Any]] = []
        for result in rows:
            row = dict(result)
            times = row.pop("history_observed_at", None) or []
            discharges = row.pop("history_discharge_m3s", None) or []
            heights = row.pop("history_water_height_m", None) or []
            row["observations"] = [
                {
                    "observed_at": observed_at,
                    "discharge_m3s": discharge,
                    "water_height_m": height,
                }
                for observed_at, discharge, height in zip(
                    times, discharges, heights
                )
            ]
            histories.append(row)
        return histories

    def load_stream_network(self) -> list[dict[str, Any]]:
        """Load the small static stream graph once per detector invocation."""
        from ecoguard.database.engine import Session

        with Session() as session:
            rows = session.execute(STREAM_NETWORK).mappings().all()
        return [dict(row) for row in rows]

    def load_latest_collector_runs(
        self, *, sources: tuple[str, ...]
    ) -> dict[str, dict[str, Any]]:
        """Return the latest recorded invocation for each requested source."""
        from ecoguard.database.engine import Session

        with Session() as session:
            rows = session.execute(
                LATEST_COLLECTOR_RUNS,
                {"sources": sources},
            ).mappings().all()
        return {row["source"]: dict(row) for row in rows}
