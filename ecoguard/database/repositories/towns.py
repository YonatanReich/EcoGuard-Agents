"""Reading the towns reference table.

Written by migration 0014 from scripts/build_towns.py. Two readers so far: the
operator's search box, which needs a name to become a camera target and a
contact card, and — later — the spread analyser, which needs the outlines
themselves.

Search is ranked rather than filtered. An operator typing "בית" means one of
forty places and wants the obvious one first, so a prefix match outranks a
match in the middle of the name, and a larger population outranks a smaller
one. Returning forty rows in arbitrary order would be technically correct and
useless.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session

# Enough to fill a dropdown without turning a one-letter query into a scan of
# the whole table's worth of rows over the wire.
DEFAULT_LIMIT = 10


def search_towns(query: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Towns whose Hebrew or English name contains `query`, best match first.

    No geometry: a search result only has to name the place and frame the map,
    and shipping 2,000 polygons to answer a keystroke would be absurd. The
    outline comes from `town_outline` once the operator has chosen.
    """
    needle = (query or "").strip()
    if not needle:
        return []

    with Session() as session:
        rows = session.execute(text("""
            SELECT town_id, name_he, name_en, place, population, households,
                   cbs_code, outline_source, fire_district, authority, authority_type, authority_phone,
                   authority_address, authority_website,
                   police_station, police_region, police_district,
                   area_km2, label_lat, label_lon,
                   min_lon, min_lat, max_lon, max_lat
            FROM towns
            WHERE name_he ILIKE :contains OR name_en ILIKE :contains
            ORDER BY
              -- A name that starts with the query is what was meant; one that
              -- merely contains it is a fallback.
              (name_he ILIKE :starts OR name_en ILIKE :starts) DESC,
              population DESC NULLS LAST,
              length(name_he)
            LIMIT :limit
        """), {
            "contains": f"%{needle}%",
            "starts": f"{needle}%",
            "limit": limit,
        }).mappings().all()

    return [_as_town(row) for row in rows]


def town_outline(town_id: str) -> dict[str, Any] | None:
    """One town as a GeoJSON Feature, outline included.

    ST_AsGeoJSON needs a geometry, not a geography, hence the cast — the column
    is geography so that the analyser's distance queries come back in metres.
    """
    with Session() as session:
        row = session.execute(text("""
            SELECT town_id, name_he, name_en, place, population, households,
                   cbs_code, outline_source, fire_district, authority, authority_type, authority_phone,
                   authority_address, authority_website,
                   police_station, police_region, police_district,
                   area_km2, label_lat, label_lon,
                   min_lon, min_lat, max_lon, max_lat,
                   ST_AsGeoJSON(outline::geometry) AS outline
            FROM towns
            WHERE town_id = :town_id
        """), {"town_id": town_id}).mappings().first()

    if row is None:
        return None

    return {
        "type": "Feature",
        "geometry": json.loads(row["outline"]),
        "properties": _as_town(row),
    }


def _as_town(row) -> dict[str, Any]:
    """One row as the shape the API and the frontend share."""
    return {
        "town_id": row["town_id"],
        "name_he": row["name_he"],
        "name_en": row["name_en"],
        "place": row["place"],
        "population": row["population"],
        "households": row["households"],
        "cbs_code": row["cbs_code"],
        # 'municipal boundary' means the outline is the jurisdiction, which is
        # larger than the built-up town; the UI qualifies the area with it.
        "outline_source": row["outline_source"],
        "fire_district": row["fire_district"],
        "authority": row["authority"],
        "authority_type": row["authority_type"],
        "authority_phone": row["authority_phone"],
        "authority_address": row["authority_address"],
        "authority_website": row["authority_website"],
        "police_station": row["police_station"],
        "police_region": row["police_region"],
        "police_district": row["police_district"],
        "area_km2": row["area_km2"],
        # Where the popup opens, and the box the camera should frame.
        "label": {"latitude": row["label_lat"], "longitude": row["label_lon"]},
        "bbox": [row["min_lon"], row["min_lat"], row["max_lon"], row["max_lat"]],
    }
