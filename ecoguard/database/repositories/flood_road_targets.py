"""PostGIS reads for flood station-to-road response-site discovery."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session


STREAM_IDENTITY = text(
    """
    SELECT station.source_station_id,
           topology.stream_context ->> 'confidence' AS match_confidence,
           (topology.stream_context -> 'stream' ->> 'stream_id')::bigint
             AS stream_id,
           (topology.stream_context -> 'stream' ->> 'water_source_id')::bigint
             AS water_source_id,
           topology.stream_context -> 'stream' ->> 'name_he' AS stream_name,
           (
             SELECT ST_AsGeoJSON(
               ST_Multi(
                 ST_CollectionExtract(
                   ST_UnaryUnion(ST_Collect(stream.geometry)),
                   2
                 )
               )
             )::jsonb
             FROM streams AS stream
             WHERE stream.water_source_id =
               (topology.stream_context -> 'stream' ->> 'water_source_id')::bigint
               AND NOT ST_IsEmpty(stream.geometry)
           ) AS geometry,
           EXISTS (
             SELECT 1
             FROM streams AS stream
             WHERE stream.water_source_id =
               (topology.stream_context -> 'stream' ->> 'water_source_id')::bigint
               AND NOT ST_IsEmpty(stream.geometry)
           ) AS has_geometry
    FROM hydrometric_stations AS station
    JOIN flood_station_topology AS topology
      ON topology.hydrometric_station_id = station.id
    WHERE station.source_station_id = :source_station_id
      AND station.flow_threshold_status = 'complete_thresholds'
      AND topology.stream_context @> '{"matched": true}'::jsonb
      AND topology.stream_context -> 'stream' ->> 'water_source_id' IS NOT NULL
    LIMIT 1
    """
)


STREAM_ROAD_CANDIDATES = text(
    """
    WITH affected_stream AS (
      SELECT ST_UnaryUnion(ST_Collect(stream.geometry)) AS geometry
      FROM streams AS stream
      WHERE stream.water_source_id = :water_source_id
    ),
    raw_intersections AS (
      SELECT road.id AS road_segment_id,
             road.source,
             road.source_feature_id,
             road.road_class,
             road.name AS road_name,
             road.road_ref,
             road.bridge,
             road.tunnel,
             road.vehicle_access,
             ST_Intersection(road.geometry, stream.geometry) AS intersection
      FROM road_segments AS road
      CROSS JOIN affected_stream AS stream
      WHERE road.road_class = ANY(:road_classes)
        AND stream.geometry IS NOT NULL
        AND road.geometry && stream.geometry
        AND ST_Intersects(road.geometry, stream.geometry)
    ),
    point_parts AS (
      SELECT intersection.*, dumped.geom AS point,
             'point'::text AS intersection_geometry
      FROM raw_intersections AS intersection
      CROSS JOIN LATERAL ST_Dump(
        ST_CollectionExtract(intersection.intersection, 1)
      ) AS dumped
      UNION ALL
      SELECT intersection.*,
             ST_LineInterpolatePoint(dumped.geom, 0.5) AS point,
             'overlap'::text AS intersection_geometry
      FROM raw_intersections AS intersection
      CROSS JOIN LATERAL ST_Dump(
        ST_CollectionExtract(intersection.intersection, 2)
      ) AS dumped
    )
    SELECT point_parts.road_segment_id,
           point_parts.source,
           point_parts.source_feature_id,
           point_parts.road_class,
           point_parts.road_name,
           point_parts.road_ref,
           point_parts.bridge,
           point_parts.tunnel,
           point_parts.vehicle_access,
           ST_Y(point_parts.point) AS latitude,
           ST_X(point_parts.point) AS longitude,
           0.0::double precision AS distance_from_station_m,
           EXISTS (
             SELECT 1
             FROM towns AS town
             WHERE ST_Covers(town.outline::geometry, point_parts.point)
           ) AS urban,
           CASE
             WHEN point_parts.bridge THEN 'bridge'
             WHEN point_parts.tunnel THEN 'tunnel'
             WHEN point_parts.intersection_geometry = 'overlap' THEN 'overlap'
             ELSE 'at_grade'
           END AS crossing_type
    FROM point_parts
    ORDER BY point_parts.road_segment_id, latitude, longitude
    """
)


STATION_ROAD_CANDIDATES = text(
    """
    WITH station AS (
      SELECT source_station_id, location
      FROM hydrometric_stations
      WHERE source_station_id = :source_station_id
        AND flow_threshold_status = 'complete_thresholds'
      LIMIT 1
    ),
    nearby AS (
      SELECT road.id AS road_segment_id,
             road.source,
             road.source_feature_id,
             road.road_class,
             road.name AS road_name,
             road.road_ref,
             road.bridge,
             road.tunnel,
             road.vehicle_access,
             station.location,
             ST_ClosestPoint(
               road.geometry,
               station.location::geometry
             ) AS point,
             ST_Distance(
               road.geometry::geography,
               station.location
             ) AS distance_from_station_m
      FROM road_segments AS road
      CROSS JOIN station
      WHERE road.road_class = ANY(:road_classes)
        AND ST_DWithin(
          road.geometry::geography,
          station.location,
          :radius_m
        )
    )
    SELECT nearby.road_segment_id,
           nearby.source,
           nearby.source_feature_id,
           nearby.road_class,
           nearby.road_name,
           nearby.road_ref,
           nearby.bridge,
           nearby.tunnel,
           nearby.vehicle_access,
           ST_Y(nearby.point) AS latitude,
           ST_X(nearby.point) AS longitude,
           nearby.distance_from_station_m,
           EXISTS (
             SELECT 1
             FROM towns AS town
             WHERE ST_Covers(town.outline::geometry, nearby.point)
           ) AS urban,
           CASE
             WHEN nearby.bridge THEN 'bridge'
             WHEN nearby.tunnel THEN 'tunnel'
             ELSE 'near_station'
           END AS crossing_type
    FROM nearby
    ORDER BY nearby.distance_from_station_m, nearby.road_segment_id
    """
)


class FloodRoadTargetRepository:
    """Resolve one station's stream and spatial road candidates."""

    def __init__(self, session_factory=Session) -> None:
        self.session_factory = session_factory

    def stream_identity(self, source_station_id: int) -> dict[str, Any] | None:
        with self.session_factory() as session:
            row = session.execute(
                STREAM_IDENTITY,
                {"source_station_id": source_station_id},
            ).mappings().first()
        return dict(row) if row is not None else None

    def stream_crossings(
        self,
        *,
        water_source_id: int,
        road_classes: Sequence[str],
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = session.execute(
                STREAM_ROAD_CANDIDATES,
                {
                    "water_source_id": water_source_id,
                    "road_classes": list(road_classes),
                },
            ).mappings().all()
        return [dict(row) for row in rows]

    def roads_near_station(
        self,
        *,
        source_station_id: int,
        radius_m: float,
        road_classes: Sequence[str],
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = session.execute(
                STATION_ROAD_CANDIDATES,
                {
                    "source_station_id": source_station_id,
                    "radius_m": radius_m,
                    "road_classes": list(road_classes),
                },
            ).mappings().all()
        return [dict(row) for row in rows]


__all__ = ["FloodRoadTargetRepository"]
