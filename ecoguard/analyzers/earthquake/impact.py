"""Small, deterministic earthquake screening-radius enrichment."""

from __future__ import annotations

from ecoguard.shared.activity import live_actor

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from ecoguard.analyzers.earthquake.intensity import (
    FELT_MMI,
    epicentral_radius_for_mmi,
    intensity_rings,
    mmi_at,
)
from ecoguard.database.repositories.area_summary import population_intersection
from ecoguard.database.repositories.towns import (
    TownIntersectionResult,
    TownLookupStatus,
    towns_intersecting,
)

LIMITATION = (
    "Shaking is modelled at rock sites from magnitude, depth and distance. It "
    "does not model soil amplification, building vulnerability, or actual "
    "damage, and for a large rupture it understates the severe zone because "
    "the source is treated as a point."
)

# Kept for callers that still ask for a magnitude-only radius. Nothing in
# this module uses it any more: the bands come from the intensity equation.
# Damage begins here. Below it shaking is felt and furniture moves; at and
# above it masonry cracks and things fall. The distinction decides what
# "people at risk" means: an M6.2 near Tiberias is felt by 7.8 million and
# threatens 862 thousand, and scoring severity on the first number would
# put every moderate earthquake at the top of the scale.
DAMAGING_MMI = 6

LEGACY_LIMITATION = (
    "Estimated Impact Area is a screening radius only; it does not model soil "
    "conditions, shaking intensity, building vulnerability, or actual damage."
)


def estimated_impact_radius_km(magnitude: float) -> float:
    """How far out an earthquake of this size is worth assessing.

    A screening radius, not a damage model. It says where to look, not what
    was damaged.
    """
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
    # Strongest first, each with the population standing in that band alone.
    # Empty when the earthquake produces no damaging shaking anywhere, which
    # is the common case below about magnitude 4.5 at normal depths.
    intensity_bands: list[dict[str, Any]]
    max_mmi: float
    # People standing where shaking is at least DAMAGING_MMI. None when the
    # population grid could not be read -- not zero, which would read as a
    # counted absence of anybody.
    population_at_damaging_intensity: int | None
    provider: str
    source: str


@live_actor("analyzer.earthquake")
def estimate_impact(
    earthquake: Mapping[str, Any],
    *,
    town_query: Callable[[dict[str, Any]], TownIntersectionResult] = towns_intersecting,
    population_query: Callable[[dict[str, Any]], Mapping[str, Any]] = population_intersection,
) -> EarthquakeImpact:
    """The area an earthquake may have affected, and the towns in it."""
    magnitude = float(earthquake["magnitude"])
    depth_km = float(earthquake["depth_km"])
    latitude = float(earthquake["latitude"])
    longitude = float(earthquake["longitude"])

    def _circle(radius_km: float) -> dict[str, Any]:
        """A circle of this radius as map geometry."""
        return impact_area_polygon(
            latitude=latitude, longitude=longitude, radius_km=radius_km
        )

    def _count(geometry: dict[str, Any]) -> int | None:
        """People inside one polygon, or None when the grid cannot be read."""
        try:
            result = population_query(geometry)
        except Exception:
            return None
        if not result.get("grid_available"):
            return None
        return round(float(result["weighted_population"]))

    # The bands an operator can act on. Below MMI IV almost nothing breaks, so
    # a weaker event has no damaging band at all rather than a small one.
    bands = intensity_rings(magnitude, depth_km)

    # Every event still needs an outline. When nothing reaches IV, the felt
    # extent is the honest one to draw -- labelled as felt, not damaging, so
    # the map does not imply a response is warranted.
    if bands:
        radius = float(bands[-1]["radius_km"])
    else:
        felt = epicentral_radius_for_mmi(magnitude, depth_km, FELT_MMI)
        if felt is None or felt <= 0:
            raise ValueError("earthquake_not_felt_at_surface")
        radius = float(felt)

    area = _circle(radius)
    towns = town_query(area)

    # Population per band, not per circle. Each ring nests inside the next, so
    # the people standing in a band are those inside it minus those inside the
    # stronger one within it. This is the PAGER method over the grid already in
    # PostGIS: exposure by shaking level, which is what "affected area and
    # severity" actually means.
    intensity_bands: list[dict[str, Any]] = []
    inner_total = 0
    inner_known = True
    for band in bands:
        cumulative = _count(_circle(float(band["radius_km"])))
        if cumulative is None:
            inner_known = False
            people = None
        else:
            people = max(0, cumulative - inner_total) if inner_known else None
            inner_total = cumulative
        intensity_bands.append({
            **band,
            "population": people,
            "population_cumulative": cumulative,
        })
    # The cumulative count at the weakest damaging band already covers every
    # stronger one inside it, so this needs no further query.
    damaging_population: int | None = None
    for band in intensity_bands:
        if int(band["mmi"]) >= DAMAGING_MMI and band["population_cumulative"] is not None:
            damaging_population = int(band["population_cumulative"])
    if not any(int(band["mmi"]) >= DAMAGING_MMI for band in intensity_bands):
        # No damaging band exists, which is a counted zero rather than an
        # unreadable one: the shaking simply never gets there.
        damaging_population = 0

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
        latitude=latitude,
        longitude=longitude,
        magnitude=magnitude,
        depth_km=depth_km,
        radius_km=radius,
        area=area,
        towns=towns,
        population_summary=population_summary,
        intensity_bands=intensity_bands,
        max_mmi=round(mmi_at(magnitude, depth_km), 1),
        population_at_damaging_intensity=damaging_population,
        provider=str(earthquake.get("provider") or "GSI"),
        source="https://seis.gsi.gov.il/fdsnws/event/1/query",
    )
