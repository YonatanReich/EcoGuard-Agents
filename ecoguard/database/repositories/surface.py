"""The static ground: its shape, and what grows on it.

Two callers want the same facts - the drawn-area summary, and an analyzer
looking at the ground around a fire - so the query lives here once.

Shape and cover belong together because neither answers anything alone. A steep
slope of bare Negev rock is not a fire; the same slope in Carmel pine is the
2010 one."""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session

# The WorldCover classes Israel actually contains, in the canonical names the
# research feature builders already use. Snow/ice, mangroves and moss/lichen
# are absent from the country and get no columns; whatever falls outside these
# lands in `unmapped`, so the fractions always sum to 1 and a gap is visible
# rather than silently missing.
COVER_COLUMNS = (
    "tree_cover",
    "shrubland",
    "grassland",
    "cropland",
    "built_up",
    "bare_sparse_vegetation",
    "permanent_water",
    "herbaceous_wetland",
    "unmapped",
)

# What a fire can actually consume. Built-up is excluded deliberately: a town
# burns, but it burns as a structure fire with different physics, different
# tactics and a different response, and folding it into the wildland fuel load
# would tell the analyser a suburb is a meadow.
BURNABLE_COLUMNS = ("tree_cover", "shrubland", "grassland", "cropland")

# Reads a CTE named `area` holding one `geom` column. Slope is averaged
# normally, but the peak is taken across cells rather than averaged: the
# steepest face inside the area is the one that decides how fast a fire leaves
# it, and it is exactly what a mean flattens away.
#
# Aspect is combined as a vector weighted by each cell's slope, the same way it
# was built: bearings do not average as numbers (350 and 10 average to 180, the
# opposite direction), and flat cells have no bearing worth counting.
#
# The cover fractions are averaged per cell rather than weighted by how much of
# each cell the polygon actually covers. Over anything larger than a few cells
# the difference is far below WorldCover's own accuracy, and it keeps this to
# one index scan.
SURFACE_AGGREGATE = """
    SELECT
      count(*)                    AS cell_count,
      avg(s.elevation_m)          AS elevation_m,
      min(s.elevation_m)          AS elevation_min_m,
      max(s.elevation_m)          AS elevation_max_m,
      avg(s.slope_deg)            AS slope_deg,
      max(s.slope_max_deg)        AS slope_max_deg,
      sum(s.slope_deg * sin(radians(s.aspect_deg))) AS aspect_east,
      sum(s.slope_deg * cos(radians(s.aspect_deg))) AS aspect_north,
      {cover}
    FROM surface_cells s, area
    WHERE ST_Intersects(s.cell, area.geom)
""".format(cover=",\n      ".join(f"avg(s.{column}) AS {column}" for column in COVER_COLUMNS))

# A fire's own footprint is rarely the ground that matters. Half a kilometre
# out is roughly where it will be within the hour on a bad day, and it is the
# slope and the fuel it is about to meet that decide whether this becomes a run.
DEFAULT_RADIUS_M = 500.0

# Below this the slope-weighted bearings cancel and the area has no single
# direction - a hilltop, a basin, or genuinely flat ground.
FLAT_EPSILON = 1e-6


def bearing_degrees(east: float, north: float) -> float:
    """Compass bearing of an (east, north) vector, in [0, 360).

    Rounded before the modulo, not after: due north comes out of atan2 as a
    tiny negative number, and `-1e-17 % 360` is 360.0 — which is outside the
    range every caller assumes and indexes a compass lookup off the end.
    """
    return round(math.degrees(math.atan2(east, north)), 6) % 360


def surface_at(
    latitude: float, longitude: float, radius_m: float = DEFAULT_RADIUS_M
) -> dict[str, Any]:
    """The ground under and around one point, for an agent holding a location.

    Args:
        latitude: WGS84 degrees north.
        longitude: WGS84 degrees east.
        radius_m: how far around the point to look. The default half kilometre
            is the ground a fire can reach soon, not just the ground it is on.

    Returns:
        dict: a `terrain` section and a `fuel` section, each shaped exactly as
            the area-summary endpoint reports them. cell_count 0 with null
            values means the point is outside the loaded service area - which
            is an answer, not a failure, and the caller should say so rather
            than treat flat-and-empty-by-default as measured.
    """
    with Session() as session:
        row = session.execute(
            text(
                """
                WITH area AS (
                  SELECT ST_Buffer(
                           ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                           :radius
                         )::geometry AS geom
                )
                """
                + SURFACE_AGGREGATE
            ),
            {"latitude": latitude, "longitude": longitude, "radius": radius_m},
        ).mappings().one()
    return {"terrain": shape_terrain(row), "fuel": shape_fuel(row)}


def shape_terrain(row) -> dict[str, Any]:
    """The shape-of-the-ground half of one aggregate row."""
    east, north = row["aspect_east"], row["aspect_north"]
    aspect = (
        None
        if east is None or north is None or math.hypot(east, north) < FLAT_EPSILON
        else bearing_degrees(east, north)
    )
    return {
        "elevation_m": _rounded(row["elevation_m"]),
        "elevation_min_m": _rounded(row["elevation_min_m"]),
        "elevation_max_m": _rounded(row["elevation_max_m"]),
        "slope_deg": _rounded(row["slope_deg"]),
        "slope_max_deg": _rounded(row["slope_max_deg"]),
        "aspect_deg": _rounded(aspect),
        # The one derived field, because it is the one every caller would
        # otherwise derive: fire runs up the slope, so it heads the way the
        # ground does not face.
        "upslope_bearing_deg": None if aspect is None else _rounded((aspect + 180) % 360),
        "cell_count": row["cell_count"],
    }


def shape_fuel(row) -> dict[str, Any]:
    """The what-grows-on-it half of one aggregate row.

    `dominant` is reported alongside the full mixture rather than instead of
    it. A single label is what a human wants first ("this is shrubland"), and
    the mixture is what the answer actually rests on ("...and a third of it is
    houses"), so dropping either one loses a question the other cannot answer.
    """
    if not row["cell_count"]:
        return {"dominant": None, "burnable_fraction": None, "built_up_fraction": None,
                "fractions": {}, "cell_count": 0}

    fractions = {column: float(row[column] or 0.0) for column in COVER_COLUMNS}
    return {
        "dominant": max(fractions, key=fractions.get),
        "burnable_fraction": _rounded_fraction(
            sum(fractions[column] for column in BURNABLE_COLUMNS)
        ),
        # Pulled out of the mixture because it is the exposure question, asked
        # on its own far more often than the rest of the breakdown.
        "built_up_fraction": _rounded_fraction(fractions["built_up"]),
        "fractions": {
            column: _rounded_fraction(value)
            for column, value in fractions.items()
            # A class with none of the area in it is noise in a prompt and in a
            # UI. Absent means zero, and every caller reads it that way.
            if value >= 0.0005
        },
        "cell_count": row["cell_count"],
    }


def _rounded(value: float | None) -> float | None:
    """A number at reporting precision, or None when there is none."""
    return None if value is None else round(float(value), 1)


def _rounded_fraction(value: float | None) -> float | None:
    """A proportion at reporting precision, or None when there is none."""
    # Three places: a thousandth of a 270 m cell is a single WorldCover pixel,
    # which is already finer than the source claims to be right about.
    return None if value is None else round(float(value), 3)
