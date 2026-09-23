"""The roads, power lines and buildings near a fire.

Read from stored map data, and reported as what is nearby rather than what is
at risk - the exposure step decides that."""

from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

from ecoguard.paths import REFERENCE

logger = logging.getLogger(__name__)

SOURCE_PATH = REFERENCE / ".osm_cache" / "nonresidential.json"

HAZARD = "hazard"
LIFE_SAFETY = "life_safety"
ECONOMIC = "economic"

CATEGORY_RANK = {HAZARD: 0, LIFE_SAFETY: 1, ECONOMIC: 2}

# OSM tag to category and to the words an operator would use. Ordered by
# specificity when read: the first rule that matches a feature wins, so
# `industrial=concrete_plant` is a hazard before `landuse=industrial` makes it
# merely economic.
RULES: tuple[tuple[str, str, str, str], ...] = (
    # (tag key, tag value, category, label)
    ("power", "plant", HAZARD, "power plant"),
    ("power", "substation", HAZARD, "electrical substation"),
    ("amenity", "fuel", HAZARD, "fuel station"),
    ("man_made", "works", HAZARD, "industrial works"),
    ("man_made", "pumping_station", HAZARD, "pumping station"),
    ("industrial", "concrete_plant", HAZARD, "concrete plant"),
    ("industrial", "scrap_yard", HAZARD, "scrap yard"),
    ("industrial", "depot", ECONOMIC, "depot"),
    ("landuse", "military", HAZARD, "military site"),
    ("military", "*", HAZARD, "military site"),
    ("amenity", "hospital", LIFE_SAFETY, "hospital"),
    ("healthcare", "hospital", LIFE_SAFETY, "hospital"),
    ("healthcare", "*", LIFE_SAFETY, "healthcare facility"),
    ("amenity", "clinic", LIFE_SAFETY, "clinic"),
    ("amenity", "school", LIFE_SAFETY, "school"),
    ("amenity", "college", LIFE_SAFETY, "college"),
    ("amenity", "university", LIFE_SAFETY, "university"),
    ("amenity", "kindergarten", LIFE_SAFETY, "kindergarten"),
    ("amenity", "refugee_site", LIFE_SAFETY, "refugee site"),
    ("amenity", "prison", LIFE_SAFETY, "prison"),
    ("landuse", "industrial", ECONOMIC, "industrial area"),
    ("landuse", "retail", ECONOMIC, "retail area"),
    ("landuse", "commercial", ECONOMIC, "commercial area"),
)

METRES_PER_DEGREE_LATITUDE = 111_320.0


def _classify(tags: Mapping[str, Any]) -> tuple[str, str] | None:
    """The category and label for one OSM feature, or None if it is neither."""
    for key, value, category, label in RULES:
        present = tags.get(key)
        if present is None:
            continue
        if value == "*" or present == value:
            return category, label
    return None


def _centroid(element: Mapping[str, Any]) -> tuple[float, float] | None:
    """One point for a feature, however Overpass happened to return it."""
    if element.get("lat") is not None and element.get("lon") is not None:
        return float(element["lat"]), float(element["lon"])
    centre = element.get("center")
    if isinstance(centre, Mapping) and centre.get("lat") is not None:
        return float(centre["lat"]), float(centre["lon"])
    geometry = element.get("geometry")
    if isinstance(geometry, list) and geometry:
        points = [
            (float(point["lat"]), float(point["lon"]))
            for point in geometry
            if isinstance(point, Mapping)
            and point.get("lat") is not None
            and point.get("lon") is not None
        ]
        if points:
            return (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
            )
    return None


@lru_cache(maxsize=1)
def load_sites() -> tuple[dict[str, Any], ...]:
    """Every classified site in the cached extract, as points.

    A polygon is reduced to its centroid. For a 20-hectare industrial estate
    that loses the fact that one corner may be inside the ring and the rest
    outside — acceptable, because the operational answer for "is there an
    industrial estate in the path" does not change with which corner, and a
    full polygon intersection would need a geometry library this package has
    deliberately avoided.
    """
    if not SOURCE_PATH.exists():
        logger.warning(
            "no infrastructure extract at %s; severity will not account for "
            "what else is in the fire's path", SOURCE_PATH,
        )
        return ()

    try:
        payload = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("could not read the infrastructure extract")
        return ()

    sites = []
    for element in payload.get("elements") or ():
        tags = element.get("tags") or {}
        classified = _classify(tags)
        if classified is None:
            continue
        point = _centroid(element)
        if point is None:
            continue
        category, label = classified
        sites.append({
            "name": tags.get("name:en") or tags.get("name") or label,
            "kind": label,
            "category": category,
            "latitude": point[0],
            "longitude": point[1],
            "osm_id": f"{element.get('type', 'way')}/{element.get('id')}",
        })
    return tuple(sites)


def sites_at_risk(
    latitude: float,
    longitude: float,
    rings: Mapping[str, Any],
    *,
    sites: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Which mapped sites the fire is in, or forecast to reach.

    Exposure classes match `exposure.py` exactly — `burning`, `likely`,
    `possible` — so a reader moves between the settlement list and this one
    without re-learning what the words mean.
    """
    from ecoguard.analyzers.fire.exposure import (
        BURNING, LIKELY, POSSIBLE, _ring_metres, point_in_ring,
    )

    records = list(sites) if sites is not None else list(load_sites())
    if not records or rings.get("status") != "ok":
        return []

    likely = _ring_metres(rings.get("likely") or [], latitude, longitude)
    possible = _ring_metres(rings.get("possible") or [], latitude, longitude)
    if not likely and not possible:
        return []

    lon_scale = METRES_PER_DEGREE_LATITUDE * math.cos(math.radians(latitude))
    at_risk = []
    for site in records:
        north = (site["latitude"] - latitude) * METRES_PER_DEGREE_LATITUDE
        east = (site["longitude"] - longitude) * lon_scale

        if likely and point_in_ring((east, north), likely):
            exposure = LIKELY
        elif possible and point_in_ring((east, north), possible):
            exposure = POSSIBLE
        else:
            continue

        at_risk.append({
            **site,
            "exposure": exposure,
            "distance_m": round(math.hypot(east, north), 1),
            "bearing_deg": round(math.degrees(math.atan2(east, north)) % 360.0, 1),
        })

    at_risk.sort(
        key=lambda item: (
            CATEGORY_RANK[item["category"]],
            0 if item["exposure"] == LIKELY else 1,
            item["distance_m"],
        )
    )
    return at_risk


def summarise(at_risk: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts per category, for scoring and for a one-line statement."""
    counts = {HAZARD: 0, LIFE_SAFETY: 0, ECONOMIC: 0}
    for site in at_risk:
        counts[site["category"]] += 1
    return {
        "counts": counts,
        "total": len(at_risk),
        # The worst thing present, which is what decides the tactic.
        "worst_category": next(
            (name for name in (HAZARD, LIFE_SAFETY, ECONOMIC) if counts[name]),
            None,
        ),
    }
