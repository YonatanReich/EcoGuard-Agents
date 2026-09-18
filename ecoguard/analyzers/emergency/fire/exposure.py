"""Who is in the way: turning a spread ring into named places and arrival times.

This is the step that makes the difference between a coordinate and a warning.
`spread.py` answers "a 2.1 km run toward bearing 264"; nobody can act on that.
This answers "Givat Shmuel, 28,500 people, the leading edge reaches its eastern
edge in about 50 minutes", which is a sentence a duty officer can do something
with.

Geometry without a geometry library, deliberately. The store has PostGIS and
that is where this runs against real population rasters — but the ring-versus-
locality test is a few hundred segment comparisons on rings this module built
itself, and requiring a live database to answer "which town is this fire in"
would make the one question worth regression-testing untestable offline. The
primitives below are the textbook ones and are exact for the simple polygons
involved.

Arrival time is read back off the ring rather than recomputed. `spread_rings`
already knows the reach on every bearing at the horizon, so the rate along a
bearing is that reach divided by the horizon, and the time to any distance on
that bearing follows. Recomputing it from the rate of spread would be a second
implementation of the same ellipse, free to disagree with the first.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ecoguard.paths import REFERENCE
from ecoguard.shared.grid import (
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
)

DEFAULT_LOCALITIES_PATH = REFERENCE / "localities.geojson"

# How a locality relates to the fire, strongest first. The order is the
# reporting order and the severity order, and both consumers rely on it.
BURNING = "burning"
LIKELY = "likely"
POSSIBLE = "possible"
EXPOSURE_RANK = {BURNING: 0, LIKELY: 1, POSSIBLE: 2}


@lru_cache(maxsize=4)
def load_localities(path: str | None = None) -> tuple[dict[str, Any], ...]:
    """Locality outlines, as (properties + rings) records.

    Cached because it is read once per incident and never changes within a
    run. Returns a tuple so the cache cannot be mutated by a caller.
    """
    source = Path(path) if path else DEFAULT_LOCALITIES_PATH
    if not source.exists():
        return ()
    payload = json.loads(source.read_text(encoding="utf-8"))
    records = []
    for feature in payload.get("features", ()):
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        coordinates = geometry.get("coordinates") or []

        # A town is one outline or several. Ariel is its built-up area plus a
        # detached industrial zone two kilometres west; reading only the first
        # part would report a fire burning in that estate as reaching nothing.
        if kind == "Polygon":
            parts = [coordinates]
        elif kind == "MultiPolygon":
            parts = coordinates
        else:
            continue

        # Outer rings only. A hole in a town outline is a park or a quarry, and
        # a fire in one of those is still a fire in the town.
        rings = tuple(
            tuple(tuple(point) for point in part[0])
            for part in parts
            if part and len(part[0]) >= 4
        )
        if not rings:
            continue

        properties = dict(feature.get("properties") or {})
        records.append({**properties, "rings": rings})
    return tuple(records)


def local_metres(
    latitude: float, longitude: float, origin_lat: float, origin_lon: float
) -> tuple[float, float]:
    """A lon/lat point as metres east and north of an origin.

    Every comparison below happens in this flat frame rather than in degrees.
    A degree of longitude in Israel is 15% shorter than a degree of latitude,
    so a ring compared in raw degrees is being compared against a map stretched
    sideways — which quietly moves every distance and every bearing.
    """
    scale = math.cos(math.radians(origin_lat))
    east = (longitude - origin_lon) * LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * scale * 1000.0
    north = (latitude - origin_lat) * LATITUDE_KM_PER_DEGREE * 1000.0
    return east, north


def point_in_ring(point: tuple[float, float], ring: Sequence[tuple[float, float]]) -> bool:
    """Ray casting: is the point inside the closed ring?"""
    x, y = point
    inside = False
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if crossing > x:
                inside = not inside
    return inside


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_cross(a, b, c, d) -> bool:
    """Whether segment ab properly crosses segment cd."""
    d1, d2 = _orientation(c, d, a), _orientation(c, d, b)
    d3, d4 = _orientation(a, b, c), _orientation(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def rings_overlap(
    first: Sequence[tuple[float, float]], second: Sequence[tuple[float, float]]
) -> bool:
    """Whether two closed rings share any area.

    Containment both ways plus an edge-crossing test. The edge test is what
    catches the case a vertex check misses — a long narrow fire run that
    crosses a town without either shape's corners landing inside the other —
    and at 72 ellipse vertices against a handful of town corners it costs
    nothing worth saving.
    """
    if any(point_in_ring(point, second) for point in first):
        return True
    if any(point_in_ring(point, first) for point in second):
        return True
    for index in range(len(first)):
        a, b = first[index], first[(index + 1) % len(first)]
        for other in range(len(second)):
            c, d = second[other], second[(other + 1) % len(second)]
            if segments_cross(a, b, c, d):
                return True
    return False


def _ring_metres(ring, origin_lat, origin_lon):
    """A [lon, lat] ring in the local metre frame, without its closing repeat."""
    points = [local_metres(point[1], point[0], origin_lat, origin_lon) for point in ring]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points


# How finely a locality outline is walked when looking for where the fire
# arrives first. 50 m is well under the accuracy of the outlines themselves and
# makes the answer independent of where the corners happen to fall.
OUTLINE_STEP_M = 50.0


def _walk_outline(points: Sequence[tuple[float, float]], step_m: float = OUTLINE_STEP_M):
    """Points along a ring's edges, not just its corners.

    Corners are the wrong places to measure from. A town wall running past the
    fire can be far closer than either of its ends, and a fire reaching the
    middle of that wall arrives long before it reaches a corner — so measuring
    at corners alone hands the duty officer minutes that do not exist.
    """
    count = len(points)
    for index in range(count):
        ax, ay = points[index]
        bx, by = points[(index + 1) % count]
        length = math.hypot(bx - ax, by - ay)
        steps = max(1, int(length / step_m))
        for step in range(steps):
            fraction = step / steps
            yield ax + (bx - ax) * fraction, ay + (by - ay) * fraction


def _approach(
    points: Sequence[tuple[float, float]], radii: Mapping[Any, float], horizon: float
) -> dict[str, Any]:
    """Where the fire comes closest to a locality, and where it gets there first.

    These are two different points and conflating them produces a contradiction
    that looks like a rounding error: the nearest corner of a town can sit on
    the slow flank of the ellipse while the fire actually arrives at a further
    point square in front of the head. Timing the nearest point then reports an
    arrival later than the horizon for a town the forecast says is inside it.

    So the nearest point answers "how far away is it" and a separately chosen
    earliest point answers "when does it get there".
    """
    nearest_distance, nearest_bearing = None, 0.0
    earliest_minutes, earliest_bearing, earliest_distance = None, None, None

    for east, north in _walk_outline(points):
        distance = math.hypot(east, north)
        bearing = math.degrees(math.atan2(east, north)) % 360.0
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance, nearest_bearing = distance, bearing
        if horizon > 0:
            reach = _reach_on_bearing(radii, bearing)
            if reach > 0:
                minutes = distance * horizon / reach
                if earliest_minutes is None or minutes < earliest_minutes:
                    earliest_minutes = minutes
                    earliest_bearing = bearing
                    earliest_distance = distance

    return {
        "distance_m": nearest_distance or 0.0,
        "bearing_deg": nearest_bearing,
        "arrival_minutes": earliest_minutes,
        "arrival_bearing_deg": earliest_bearing,
        "arrival_distance_m": earliest_distance,
    }


def _reach_on_bearing(radii: Mapping[Any, float], bearing: float) -> float:
    """The ring's reach on the bearing nearest the one asked for."""
    if not radii:
        return 0.0
    best_key = min(
        radii, key=lambda key: abs((float(key) - bearing + 180.0) % 360.0 - 180.0)
    )
    return float(radii[best_key])


def _nearest_approach(
    outlines: Sequence[Sequence[tuple[float, float]]],
    radii: Mapping[Any, float],
    horizon: float,
) -> dict[str, Any]:
    """`_approach` across every part of a locality, worst case per question.

    Distance and arrival are minimised independently, because they can belong
    to different parts: a fire west of Ariel is nearest to the industrial
    estate while the head of the run reaches the town itself first. Taking
    whichever part is closest and reading both answers off it would report an
    arrival time for the wrong piece of ground.
    """
    best: dict[str, Any] | None = None
    for outline in outlines:
        approach = _approach(outline, radii, horizon)
        if best is None:
            best = approach
            continue

        if approach["distance_m"] < best["distance_m"]:
            best["distance_m"] = approach["distance_m"]
            best["bearing_deg"] = approach["bearing_deg"]

        theirs, ours = approach["arrival_minutes"], best["arrival_minutes"]
        if theirs is not None and (ours is None or theirs < ours):
            best["arrival_minutes"] = theirs
            best["arrival_bearing_deg"] = approach["arrival_bearing_deg"]
            best["arrival_distance_m"] = approach["arrival_distance_m"]

    return best or {"distance_m": 0.0, "bearing_deg": 0.0, "arrival_minutes": None,
                    "arrival_bearing_deg": None, "arrival_distance_m": None}


def localities_at_risk(
    latitude: float,
    longitude: float,
    rings: Mapping[str, Any],
    *,
    localities: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Which settlements the fire is in or heading for, worst first.

    Args:
        latitude, longitude: the ignition point the rings were grown from.
        rings: a `spread.spread_rings` result.
        localities: outlines to test against. Defaults to the reference file;
            passed explicitly by tests and by anything scoping to a district.

    Returns:
        list of dicts, each naming a locality, how it is exposed, how far the
        nearest part of it is, on what bearing, and the estimated minutes until
        the front reaches it. `arrival_minutes` is None for a locality the fire
        is already inside, and for one only the `possible` ring reaches — in
        that case the arrival time is a property of a wind error rather than of
        the forecast, and putting a number on it would overstate what is known.
    """
    records = list(localities) if localities is not None else list(load_localities())
    if not records:
        return []

    likely = _ring_metres(rings.get("likely") or [], latitude, longitude)
    possible = _ring_metres(rings.get("possible") or [], latitude, longitude)
    radii = (rings.get("radii_m") or {}).get("likely") or {}
    horizon = float(rings.get("horizon_minutes") or 0.0)

    at_risk = []
    for record in records:
        outlines = [_ring_metres(ring, latitude, longitude) for ring in record["rings"]]
        outlines = [outline for outline in outlines if outline]
        if not outlines:
            continue

        # Any part burning means the town is burning; any part in the ring
        # means the town is in the ring.
        if any(point_in_ring((0.0, 0.0), outline) for outline in outlines):
            status = BURNING
        elif likely and any(rings_overlap(likely, outline) for outline in outlines):
            status = LIKELY
        elif possible and any(rings_overlap(possible, outline) for outline in outlines):
            status = POSSIBLE
        else:
            continue

        approach = _nearest_approach(outlines, radii, horizon)
        arrival = approach["arrival_minutes"] if status == LIKELY else None

        at_risk.append({
            "locality_id": record.get("locality_id"),
            "name": record.get("name"),
            "name_he": record.get("name_he"),
            "population": record.get("population"),
            "exposure": status,
            "distance_m": round(approach["distance_m"], 1),
            "bearing_deg": round(approach["bearing_deg"], 1),
            "arrival_minutes": None if arrival is None else round(arrival, 1),
            "arrival_bearing_deg": (
                None
                if arrival is None or approach["arrival_bearing_deg"] is None
                else round(approach["arrival_bearing_deg"], 1)
            ),
        })

    at_risk.sort(key=lambda item: (EXPOSURE_RANK[item["exposure"]], item["distance_m"]))
    return at_risk


def population_at_risk(at_risk: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Residents of each exposed locality, totalled by how it is exposed.

    Whole-locality populations, not the count inside the ring. A fire reaching
    the edge of Givat Shmuel is an event for Givat Shmuel, and apportioning
    28,500 people by what fraction of the municipal outline the ellipse happens
    to cover would invent a precision the coarse outlines cannot support. The
    per-hectare count is what `population_cells` is for, over the ring itself,
    and that is a separate number with a separate meaning.
    """
    totals = {BURNING: 0, LIKELY: 0, POSSIBLE: 0}
    for item in at_risk:
        totals[item["exposure"]] += int(item.get("population") or 0)
    return totals
