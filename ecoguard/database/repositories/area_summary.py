"""Aggregate everything we store over one user-drawn polygon.

This is the read side of the drawing tool: the user encloses an area on the
map and gets back what is inside it — how many people, what the weather is
doing, how dangerous the fire weather is, which emergency stations are in
reach. Every number comes from data already in the store, so drawing an area
costs one round trip and no upstream API calls.

The two aggregations are deliberately different, because the two datasets are:

  * population_cells is a fine grid of counts, so it is summed with area
    weighting — a cell half inside the polygon contributes half its people.
  * observations sit on the 5 km service-area grid, one sample per cell, and a
    sample is a point measurement rather than a quantity spread over the cell.
    Those are averaged, over every cell within half a grid step of the polygon
    so that a polygon smaller than one cell still resolves to the cell it is
    drawn inside instead of returning nothing.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.database.repositories.observations import FWI_BAND_VALUE
from ecoguard.database.repositories.surface import SURFACE_AGGREGATE, shape_fuel, shape_terrain
from ecoguard.shared.grid import GRID_RESOLUTION_KM

# Half a grid step. A weather cell this close to the polygon is the cell the
# polygon is standing on, even when the polygon is far too small to contain the
# sample point itself.
SAMPLE_RADIUS_M = GRID_RESOLUTION_KM * 1000 / 2

# How stale a weather reading may be and still count as "now". The collector
# writes complete hours only and re-reads a six-hour window, so anything older
# than this means collection is down, and reporting nothing is better than
# reporting yesterday's temperature as the current one.
WEATHER_MAX_AGE_HOURS = 6

# The drawn shape, cleaned. Freehand drawing self-intersects constantly — a
# wobbling hand crossing its own line is the normal case, not an error — and
# ST_Intersection rejects an invalid polygon outright. ST_MakeValid splits it
# into valid pieces; CollectionExtract(..., 3) keeps the polygonal ones and
# drops the stray lines a pinched-off loop leaves behind.
AREA_CTE = """
    WITH area AS (
      SELECT ST_CollectionExtract(
               ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326)),
               3
             ) AS geom
    )
"""


def _population(session, geojson: str) -> float:
    """People inside the polygon, area-weighted across partly covered cells.

    The weighting assumes people are spread evenly inside a single 100 m cell,
    which is the same assumption the source raster already makes. Above that
    scale the answer is as good as the grid.
    """
    return session.execute(
        text(
            AREA_CTE
            + """
            SELECT coalesce(sum(
                     cells.population
                     * ST_Area(ST_Intersection(cells.cell, area.geom))
                     / ST_Area(cells.cell)
                   ), 0)
            FROM population_cells cells, area
            WHERE ST_Intersects(cells.cell, area.geom)
            """
        ),
        {"geojson": geojson},
    ).scalar_one()


def population_intersection(
    geometry: dict[str, Any], *, session_factory=Session
) -> dict[str, Any]:
    """Read the shared population grid for one polygon without hiding absence.

    This is the population-only counterpart to :func:`summarize_area`.  Its
    explicit global-grid check distinguishes a genuine zero inside a query
    polygon from an empty/unloaded ``population_cells`` table.  It performs
    one SELECT and never mutates the shared reference data.
    """

    geojson = json.dumps(geometry)
    statement = text(
        AREA_CTE
        + """
        SELECT
          EXISTS (SELECT 1 FROM population_cells LIMIT 1) AS grid_available,
          (
            SELECT count(*)
            FROM population_cells cells, area
            WHERE ST_Intersects(cells.cell, area.geom)
          ) AS intersected_cell_count,
          (
            SELECT coalesce(sum(
                     cells.population
                     * ST_Area(ST_Intersection(cells.cell, area.geom))
                     / ST_Area(cells.cell)
                   ), 0)
            FROM population_cells cells, area
            WHERE ST_Intersects(cells.cell, area.geom)
          ) AS weighted_population
        FROM area
        """
    )
    with session_factory() as session:
        row = session.execute(statement, {"geojson": geojson}).mappings().one()
    return {
        "grid_available": bool(row["grid_available"]),
        "intersected_cell_count": int(row["intersected_cell_count"]),
        "weighted_population": float(row["weighted_population"]),
    }


def _weather(session, geojson: str) -> dict[str, Any]:
    """Mean current conditions over the weather cells covering the polygon.

    DISTINCT ON picks each cell's newest reading before averaging, so one cell
    that lagged an hour behind does not drag the mean toward its own timestamp.

    Wind direction is averaged as a vector rather than as a number: the plain
    mean of 350 and 10 degrees is 180, which points the wind the wrong way.
    """
    row = session.execute(
        text(
            AREA_CTE
            + """
            , latest AS (
              SELECT DISTINCT ON (o.cell_id) o.cell_id, o.observed_at, o.payload
              FROM observations o, area
              WHERE o.source = 'weather'
                AND o.observed_at >= now() - make_interval(hours => :max_age)
                AND ST_DWithin(o.location, area.geom::geography, :radius)
              ORDER BY o.cell_id, o.observed_at DESC
            )
            SELECT
              count(*)                                                  AS cell_count,
              max(observed_at)                                          AS observed_at,
              avg((payload->>'temperature_2m')::double precision)       AS temperature_c,
              avg((payload->>'relative_humidity_2m')::double precision) AS humidity_percent,
              avg((payload->>'wind_speed_10m')::double precision)       AS wind_speed_kmh,
              max((payload->>'wind_gusts_10m')::double precision)       AS wind_gust_max_kmh,
              avg((payload->>'precipitation')::double precision)        AS precipitation_mm,
              mod(
                degrees(atan2(
                  avg(sin(radians((payload->>'wind_direction_10m')::double precision))),
                  avg(cos(radians((payload->>'wind_direction_10m')::double precision)))
                ))::numeric + 360, 360
              )::double precision                                       AS wind_direction_deg
            FROM latest
            """
        ),
        {"geojson": geojson, "radius": SAMPLE_RADIUS_M, "max_age": WEATHER_MAX_AGE_HOURS},
    ).mappings().one()

    observed_at = row["observed_at"]
    return {
        **{
            key: _rounded(row[key])
            for key in (
                "temperature_c",
                "humidity_percent",
                "wind_speed_kmh",
                "wind_gust_max_kmh",
                "precipitation_mm",
                "wind_direction_deg",
            )
        },
        "observed_at": observed_at.isoformat() if observed_at else None,
        # Callers need to know how much grid is behind the mean. One cell over
        # a city-block polygon is a very different claim from forty over a
        # district, and both are legitimate answers to draw.
        "cell_count": row["cell_count"],
    }


def _fire_danger(session, geojson: str) -> dict[str, Any]:
    """Mean and worst Fire Weather Index band over the same cells.

    The source is a categorised WMS raster, so each cell stores a band name and
    the mean is taken over the band midpoints the rest of the app already uses.
    The worst band is reported alongside it because an average hides the one
    extreme cell that is the reason to look.
    """
    rows = session.execute(
        text(
            AREA_CTE
            + """
            , latest AS (
              SELECT DISTINCT ON (o.cell_id) o.cell_id, o.observed_at, o.payload
              FROM observations o, area
              WHERE o.source = 'fire_weather'
                AND ST_DWithin(o.location, area.geom::geography, :radius)
              ORDER BY o.cell_id, o.observed_at DESC
            )
            SELECT payload->>'danger_level' AS danger_level, observed_at FROM latest
            """
        ),
        {"geojson": geojson, "radius": SAMPLE_RADIUS_M},
    ).mappings().all()

    values = [
        (FWI_BAND_VALUE[row["danger_level"]], row["danger_level"])
        for row in rows
        if row["danger_level"] in FWI_BAND_VALUE
    ]
    if not values:
        return {"fwi": None, "worst_level": None, "cell_count": 0, "observed_at": None}

    worst = max(values)
    return {
        "fwi": _rounded(sum(value for value, _ in values) / len(values)),
        "worst_level": worst[1],
        "cell_count": len(values),
        "observed_at": max(row["observed_at"] for row in rows).isoformat(),
    }


def _surface(session, geojson: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The static ground inside the polygon: its shape, and what grows on it.

    Like population this is a grid of footprints, so it is intersected rather
    than sampled within a radius — the ground has no observation time and no
    gaps to reach across. One query returns both halves because they are one
    row in one table; the aggregate itself lives in the surface repository,
    which the agents call directly around a fire's coordinate.
    """
    row = session.execute(
        text(AREA_CTE + SURFACE_AGGREGATE), {"geojson": geojson}
    ).mappings().one()
    return shape_terrain(row), shape_fuel(row)


def _stations(session, geojson: str) -> dict[str, int]:
    """How many of each service's stations stand inside the polygon."""
    row = session.execute(
        text(
            AREA_CTE
            + """
            SELECT
              (SELECT count(*) FROM fire_stations s, area
                 WHERE s.location IS NOT NULL
                   AND ST_Covers(area.geom, s.location::geometry)) AS fire,
              (SELECT count(*) FROM police_stations s, area
                 WHERE s.location IS NOT NULL
                   AND ST_Covers(area.geom, s.location::geometry)) AS police,
              (SELECT count(*) FROM mda_stations s, area
                 WHERE s.location IS NOT NULL
                   AND ST_Covers(area.geom, s.location::geometry)) AS mda
            """
        ),
        {"geojson": geojson},
    ).mappings().one()
    return {"fire": row["fire"], "police": row["police"], "mda": row["mda"]}


def _area_km2(session, geojson: str) -> float:
    """The polygon's true area on the spheroid, not its area in degrees."""
    return session.execute(
        text(AREA_CTE + "SELECT ST_Area(geom::geography) / 1e6 FROM area"),
        {"geojson": geojson},
    ).scalar_one()


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 1)


def summarize_area(geometry: dict[str, Any]) -> dict[str, Any]:
    """Everything we know about the inside of one GeoJSON polygon.

    Args:
        geometry: a GeoJSON Polygon, already validated by the caller. Passed to
            PostGIS as a bound parameter, never interpolated into the SQL.

    Returns:
        dict: area_km2, population, weather, fire_danger and stations. Sections
            with no data behind them report null values and a cell_count of 0
            rather than being omitted, so the UI can say "no reading here"
            instead of silently dropping a row.
    """
    geojson = json.dumps(geometry)
    with Session() as session:
        terrain, fuel = _surface(session, geojson)
        return {
            "area_km2": _rounded(_area_km2(session, geojson)),
            # People do not come in tenths, and the raster's own precision is
            # nowhere near one person anyway.
            "population": round(_population(session, geojson)),
            "weather": _weather(session, geojson),
            "fire_danger": _fire_danger(session, geojson),
            "terrain": terrain,
            "fuel": fuel,
            "stations": _stations(session, geojson),
        }
