"""Small, deterministic earthquake screening-radius enrichment."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from ecoguard.database.repositories.area_summary import population_intersection
from ecoguard.database.repositories.towns import (
    TownIntersectionResult,
    TownLookupStatus,
    towns_intersecting,
)

LIMITATION = (
    "Estimated Impact Area is a screening radius only; it does not model soil "
    "conditions, shaking intensity, building vulnerability, or actual damage."
)


def estimated_impact_radius_km(magnitude: float) -> float:
    if magnitude < 3.5:
        return 5.0
    if magnitude < 4.5:
        return 10.0
    if magnitude < 5.5:
        return 25.0
    return 50.0


def impact_area_polygon(
    *, latitude: float, longitude: float, radius_km: float, vertices: int = 64
) -> dict[str, Any]:
    """Return a deterministic geodesic GeoJSON circle approximation."""

    earth_radius_km = 6371.0088
    angular_distance = radius_km / earth_radius_km
    lat1 = math.radians(latitude)
    lon1 = math.radians(longitude)
    coordinates = []
    for index in range(vertices):
        bearing = 2 * math.pi * index / vertices
        lat2 = math.asin(
            math.sin(lat1) * math.cos(angular_distance)
            + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
        )
        lon2 = lon1 + math.atan2(
            math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
            math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
        )
        coordinates.append([math.degrees(lon2), math.degrees(lat2)])
    coordinates.append(coordinates[0])
    return {"type": "Polygon", "coordinates": [coordinates]}


@dataclass(frozen=True)
class EarthquakeImpact:
    provider_event_id: str
    observed_at: datetime
    latitude: float
    longitude: float
    magnitude: float
    depth_km: float
    radius_km: float
    area: dict[str, Any]
    towns: TownIntersectionResult
    population_summary: dict[str, Any]
    provider: str
    source: str


def estimate_impact(
    earthquake: Mapping[str, Any],
    *,
    town_query: Callable[[dict[str, Any]], TownIntersectionResult] = towns_intersecting,
    population_query: Callable[[dict[str, Any]], Mapping[str, Any]] = population_intersection,
) -> EarthquakeImpact:
    radius = estimated_impact_radius_km(float(earthquake["magnitude"]))
    area = impact_area_polygon(
        latitude=float(earthquake["latitude"]),
        longitude=float(earthquake["longitude"]),
        radius_km=radius,
    )
    towns = town_query(area)
    try:
        population = population_query(area)
        if population.get("grid_available"):
            population_summary = {
                "status": "available",
                "estimated_population": round(float(population["weighted_population"])),
                "intersected_cell_count": int(population["intersected_cell_count"]),
                "reason": None,
            }
        else:
            population_summary = {
                "status": "unavailable",
                "estimated_population": None,
                "intersected_cell_count": None,
                "reason": "population_grid_not_loaded",
            }
    except Exception:
        population_summary = {
            "status": "unavailable",
            "estimated_population": None,
            "intersected_cell_count": None,
            "reason": "population_repository_unavailable",
        }
    return EarthquakeImpact(
        provider_event_id=str(earthquake["provider_event_id"]),
        observed_at=datetime.fromisoformat(str(earthquake["observed_at"]).replace("Z", "+00:00")),
        latitude=float(earthquake["latitude"]),
        longitude=float(earthquake["longitude"]),
        magnitude=float(earthquake["magnitude"]),
        depth_km=float(earthquake["depth_km"]),
        radius_km=radius,
        area=area,
        towns=towns,
        population_summary=population_summary,
        provider=str(earthquake.get("provider") or "GSI"),
        source="https://seis.gsi.gov.il/fdsnws/event/1/query",
    )
