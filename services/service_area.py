"""Runtime EcoGuard operational service-area geometry."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from services.grid_manager import (
    GRID_RESOLUTION_KM,
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
)


DEFAULT_SERVICE_AREA_PATH = Path("data/reference/ecoguard_service_area.geojson")
_EPSILON = 1e-10
DEFAULT_MINIMUM_CELL_OVERLAP = 0.25


class ServiceAreaError(RuntimeError):
    pass


def _point_on_segment(x: float, y: float, start: list[float], end: list[float]) -> bool:
    x1, y1 = float(start[0]), float(start[1])
    x2, y2 = float(end[0]), float(end[1])
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > _EPSILON:
        return False
    return min(x1, x2) - _EPSILON <= x <= max(x1, x2) + _EPSILON and min(y1, y2) - _EPSILON <= y <= max(y1, y2) + _EPSILON


def _ring_contains_or_touches(ring: list[list[float]], longitude: float, latitude: float) -> tuple[bool, bool]:
    inside = False
    for index in range(len(ring) - 1):
        start, end = ring[index], ring[index + 1]
        if _point_on_segment(longitude, latitude, start, end):
            return True, True
        x1, y1 = float(start[0]), float(start[1])
        x2, y2 = float(end[0]), float(end[1])
        if (y1 > latitude) != (y2 > latitude):
            crossing_x = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing_x:
                inside = not inside
    return inside, False


def _polygon_contains_or_touches(polygon: list[list[list[float]]], longitude: float, latitude: float) -> bool:
    outer_inside, outer_boundary = _ring_contains_or_touches(polygon[0], longitude, latitude)
    if outer_boundary:
        return True
    if not outer_inside:
        return False
    for hole in polygon[1:]:
        hole_inside, hole_boundary = _ring_contains_or_touches(hole, longitude, latitude)
        if hole_boundary:
            return True
        if hole_inside:
            return False
    return True


def _clip_ring_to_rectangle(
    ring: list[list[float]], left: float, bottom: float, right: float, top: float,
) -> list[tuple[float, float]]:
    points = [(float(point[0]), float(point[1])) for point in ring]
    if points and points[0] == points[-1]:
        points.pop()

    def clip(points, inside, intersect):
        if not points:
            return []
        output = []
        previous = points[-1]
        previous_inside = inside(previous)
        for current in points:
            current_inside = inside(current)
            if current_inside:
                if not previous_inside:
                    output.append(intersect(previous, current))
                output.append(current)
            elif previous_inside:
                output.append(intersect(previous, current))
            previous, previous_inside = current, current_inside
        return output

    def vertical(x_value):
        def intersection(start, end):
            portion = (x_value - start[0]) / (end[0] - start[0])
            return x_value, start[1] + portion * (end[1] - start[1])
        return intersection

    def horizontal(y_value):
        def intersection(start, end):
            portion = (y_value - start[1]) / (end[1] - start[1])
            return start[0] + portion * (end[0] - start[0]), y_value
        return intersection

    points = clip(points, lambda p: p[0] >= left, vertical(left))
    points = clip(points, lambda p: p[0] <= right, vertical(right))
    points = clip(points, lambda p: p[1] >= bottom, horizontal(bottom))
    return clip(points, lambda p: p[1] <= top, horizontal(top))


def _ring_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )) / 2


class ServiceArea:
    """A GeoJSON Polygon/MultiPolygon used only as an operational area."""

    def __init__(self, path: Path | str = DEFAULT_SERVICE_AREA_PATH):
        self.path = Path(path)
        try:
            collection: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            features = collection["features"]
            if len(features) != 1:
                raise ValueError
            geometry = features[0]["geometry"]
            self.geometry = geometry
            if geometry["type"] == "Polygon":
                self.polygons = [geometry["coordinates"]]
            elif geometry["type"] == "MultiPolygon":
                self.polygons = geometry["coordinates"]
            else:
                raise ValueError
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ServiceAreaError("EcoGuard service-area GeoJSON is missing or invalid") from None

    def contains_or_touches(self, latitude: float, longitude: float) -> bool:
        """Include a 5 km cell when its centroid is inside or on the boundary."""
        return any(_polygon_contains_or_touches(polygon, longitude, latitude) for polygon in self.polygons)

    def cell_overlap_fraction(
        self, latitude: float, longitude: float, *, resolution_km: float = GRID_RESOLUTION_KM,
    ) -> float:
        """Return planar footprint overlap; sufficient for a local 5 km WGS84 cell."""
        latitude_half = resolution_km / LATITUDE_KM_PER_DEGREE / 2
        longitude_half = resolution_km / (
            LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * math.cos(math.radians(latitude))
        ) / 2
        left, right = longitude - longitude_half, longitude + longitude_half
        bottom, top = latitude - latitude_half, latitude + latitude_half
        overlap = 0.0
        for polygon in self.polygons:
            overlap += _ring_area(_clip_ring_to_rectangle(polygon[0], left, bottom, right, top))
            for hole in polygon[1:]:
                overlap -= _ring_area(_clip_ring_to_rectangle(hole, left, bottom, right, top))
        footprint = (right - left) * (top - bottom)
        return max(0.0, min(1.0, overlap / footprint))

    def includes_cell(
        self,
        latitude: float,
        longitude: float,
        *,
        resolution_km: float = GRID_RESOLUTION_KM,
        minimum_overlap: float = DEFAULT_MINIMUM_CELL_OVERLAP,
    ) -> bool:
        """Apply the shared centroid-or-25%-footprint operational-area rule."""
        return self.contains_or_touches(latitude, longitude) or (
            self.cell_overlap_fraction(latitude, longitude, resolution_km=resolution_km)
            + _EPSILON >= minimum_overlap
        )
