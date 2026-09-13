"""Pydantic transport schema for the drawn-area summary endpoint.

The polygon arrives from a drawing tool in the browser, which makes it
untrusted input reaching PostGIS. It is bound as a parameter, never
interpolated, so injection is not the risk; the risks are a shape PostGIS
cannot parse, a freehand trace with tens of thousands of vertices, and a
polygon covering half the planet. All three are refused here, before the query
runs, so the endpoint answers 422 with a reason rather than timing out.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

# Israel's bounding box, the same one the coordinate endpoints enforce: it
# matches the product scope and keeps the query inside the ground our data
# actually covers.
MIN_LATITUDE, MAX_LATITUDE = 29.45, 33.35
MIN_LONGITUDE, MAX_LONGITUDE = 34.26, 35.90

# A freehand trace is decimated in the browser, but a hostile or buggy client
# is not. Two thousand vertices is far more detail than a 100 m population grid
# can answer to, and it keeps ST_Intersection's cost bounded.
MAX_VERTICES = 2_000


class AreaSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geometry: dict[str, Any]

    @field_validator("geometry")
    @classmethod
    def _must_be_a_polygon_inside_israel(cls, geometry: dict[str, Any]) -> dict[str, Any]:
        if geometry.get("type") != "Polygon":
            raise ValueError("geometry must be a GeoJSON Polygon")

        rings = geometry.get("coordinates")
        if not isinstance(rings, list) or not rings:
            raise ValueError("Polygon needs at least an outer ring")

        vertices = 0
        for ring in rings:
            # Four is the minimum a closed triangle takes: three corners plus
            # the repeat of the first, which GeoJSON requires.
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("each ring needs at least four positions")

            for position in ring:
                if (
                    not isinstance(position, (list, tuple))
                    or len(position) < 2
                    or not all(isinstance(value, (int, float)) for value in position[:2])
                ):
                    raise ValueError("each position must be [longitude, latitude]")

                longitude, latitude = position[0], position[1]
                if not (MIN_LONGITUDE <= longitude <= MAX_LONGITUDE):
                    raise ValueError("longitude must be within Israel's borders")
                if not (MIN_LATITUDE <= latitude <= MAX_LATITUDE):
                    raise ValueError("latitude must be within Israel's borders")

            if list(ring[0][:2]) != list(ring[-1][:2]):
                raise ValueError("each ring must be closed — first position repeated last")

            vertices += len(ring)

        if vertices > MAX_VERTICES:
            raise ValueError(f"polygon has {vertices} vertices; the limit is {MAX_VERTICES}")

        return geometry


class AreaWeather(BaseModel):
    temperature_c: float | None
    humidity_percent: float | None
    wind_speed_kmh: float | None
    wind_gust_max_kmh: float | None
    wind_direction_deg: float | None
    precipitation_mm: float | None
    observed_at: str | None
    cell_count: int


class AreaFireDanger(BaseModel):
    fwi: float | None
    worst_level: str | None
    cell_count: int
    observed_at: str | None


class AreaTerrain(BaseModel):
    elevation_m: float | None
    elevation_min_m: float | None
    elevation_max_m: float | None
    slope_deg: float | None
    slope_max_deg: float | None
    # The bearing the ground faces, and the bearing a fire runs — opposite
    # directions, both reported so no client has to know that fire goes uphill.
    aspect_deg: float | None
    upslope_bearing_deg: float | None
    cell_count: int


class AreaFuel(BaseModel):
    # The single label a human reads first, then the mixture the answer rests
    # on. Classes with none of the area in them are absent rather than zero.
    dominant: str | None
    burnable_fraction: float | None
    built_up_fraction: float | None
    fractions: dict[str, float]
    cell_count: int


class AreaSummaryResponse(BaseModel):
    area_km2: float
    population: int
    weather: AreaWeather
    fire_danger: AreaFireDanger
    terrain: AreaTerrain
    fuel: AreaFuel
    stations: dict[Literal["fire", "police", "mda"], int]
