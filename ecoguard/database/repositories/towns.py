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
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ecoguard.database.engine import Session

# Enough to fill a dropdown without turning a one-letter query into a scan of
# the whole table's worth of rows over the wire.
DEFAULT_LIMIT = 10


class TownLookupStatus(StrEnum):
    SUCCESS_WITH_RESULTS = "SUCCESS_WITH_RESULTS"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"
    REFERENCE_DATA_NOT_LOADED = "REFERENCE_DATA_NOT_LOADED"
    UNAVAILABLE = "UNAVAILABLE"


class TownCandidate(BaseModel):
    """Settlement metadata needed by Air Pollution spatial screening."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    town_id: str
    name_he: str
    name_en: str
    place: str | None = None
    cbs_code: str | None = None
    population: int | None = Field(default=None, ge=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    distance_m: float = Field(ge=0)
    outline_source: str | None = None
    authority: str | None = None
    authority_type: str | None = None
    fire_district: str | None = None
    police_station: str | None = None


class TownLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: TownLookupStatus
    candidates: list[TownCandidate] = Field(default_factory=list)
    source: str = "shared_postgis_towns"
    reason: str | None = None


_TOWNS_EXISTS_SQL = text(
    "SELECT to_regclass('public.towns') IS NOT NULL AS layer_exists"
)
_TOWNS_POPULATED_SQL = text("SELECT EXISTS (SELECT 1 FROM towns LIMIT 1)")
_NEARBY_TOWNS_SQL = text(
    """
    WITH origin AS (
      SELECT ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
        AS point
    )
    SELECT
      town_id,
      name_he,
      name_en,
      place,
      cbs_code,
      population,
      label_lat AS latitude,
      label_lon AS longitude,
      ST_Distance(outline, origin.point) AS distance_m,
      outline_source,
      authority,
      authority_type,
      fire_district,
      police_station
    FROM towns, origin
    WHERE ST_DWithin(outline, origin.point, :radius_m)
    ORDER BY distance_m, town_id
    """
)


def nearby_towns(
    *,
    latitude: float,
    longitude: float,
    radius_m: float,
    session_factory=Session,
) -> TownLookupResult:
    """Return towns whose authoritative outline is near the requested point.

    Candidate inclusion and distance use the stored national town polygon. The
    stored label point is returned separately because Air Pollution's existing
    directional ranking is point-based.
    """

    try:
        with session_factory() as session:
            if not session.execute(_TOWNS_EXISTS_SQL).scalar_one():
                return TownLookupResult(
                    status=TownLookupStatus.REFERENCE_DATA_NOT_LOADED,
                    reason="reference_data_not_loaded",
                )
            if not session.execute(_TOWNS_POPULATED_SQL).scalar_one():
                return TownLookupResult(
                    status=TownLookupStatus.REFERENCE_DATA_NOT_LOADED,
                    reason="reference_data_not_loaded",
                )
            rows = session.execute(
                _NEARBY_TOWNS_SQL,
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "radius_m": radius_m,
                },
            ).mappings().all()
            candidates = [TownCandidate.model_validate(dict(row)) for row in rows]
    except (SQLAlchemyError, ValidationError, TypeError, ValueError):
        return TownLookupResult(
            status=TownLookupStatus.UNAVAILABLE,
            reason="town_repository_unavailable",
        )

    return TownLookupResult(
        status=(
            TownLookupStatus.SUCCESS_WITH_RESULTS
            if candidates
            else TownLookupStatus.SUCCESS_EMPTY
        ),
        candidates=candidates,
    )


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


def towns_with_outlines_near(
    *, latitude: float, longitude: float, radius_m: float
) -> tuple[dict[str, Any], ...]:
    """Settlements near a point, as the record shape fire exposure testing reads.

    The fire spread analyser tests its rings against locality outlines, and its
    own module defaults to a six-feature committed fixture. This is the
    national set, and it carries the three things that make an exposure line
    actionable rather than merely informative: the local authority's telephone
    number, the fire district, and the responsible police station.

    `rings` matches `exposure.load_localities` exactly — outer rings only, one
    entry per part, points as (longitude, latitude). Holes are dropped for the
    reason migration 0014 gives: a hole in a town outline is a park or a
    quarry, and a fire in one of those is still a fire in the town.
    """
    with Session() as session:
        rows = session.execute(
            text("""
                SELECT town_id, name_he, name_en, population, place,
                       fire_district, authority, authority_type,
                       authority_phone, authority_website, police_station,
                       label_lat, label_lon,
                       ST_Area(outline) / 1e6 AS outline_km2,
                       ST_AsGeoJSON(outline::geometry) AS outline
                FROM towns
                WHERE ST_DWithin(outline, ST_SetSRID(
                          ST_MakePoint(:longitude, :latitude), 4326)::geography, :radius_m)
            """),
            {"latitude": latitude, "longitude": longitude, "radius_m": radius_m},
        ).mappings().all()

    records = []
    for row in rows:
        # Some rows carry their regional council's whole area as their own
        # outline. Fourteen villages around Petah Tikva each hold the same
        # 277 km2 polygon, so a fire anywhere inside it was reported as burning
        # in all fourteen and their populations summed. The polygon says
        # nothing about where any of those villages actually is.
        #
        # Their own label point does. So a shared outline is replaced by a
        # nominal circle around that point: a coarse footprint in the right
        # place, instead of a precise-looking one in the wrong place.
        if _is_jurisdiction(row):
            record = _nominal_footprint(row)
            if record is not None:
                records.append(record)
            continue

        geometry = json.loads(row["outline"]) if row["outline"] else {}
        kind = geometry.get("type")
        coordinates = geometry.get("coordinates") or []
        if kind == "Polygon":
            parts = [coordinates]
        elif kind == "MultiPolygon":
            parts = coordinates
        else:
            continue

        rings = tuple(
            tuple(tuple(point) for point in part[0])
            for part in parts
            if part and len(part[0]) >= 4
        )
        if not rings:
            continue

        records.append({
            "locality_id": row["town_id"],
            # English where there is one, Hebrew otherwise. An operator reading
            # a mixed list wants one column of names, and a blank is worse than
            # the other language.
            "name": row["name_en"] or row["name_he"],
            "name_he": row["name_he"],
            "population": row["population"],
            "place": row["place"],
            "authority": row["authority"],
            "authority_type": row["authority_type"],
            "authority_phone": row["authority_phone"],
            "authority_website": row["authority_website"],
            "fire_district": row["fire_district"],
            "police_station": row["police_station"],
            "rings": rings,
        })
    return tuple(records)


# How wide to draw a settlement that has no outline of its own. Most Israeli
# moshavim and kibbutzim sit inside a few hundred metres; 400 m is a footprint
# that neither vanishes nor swallows its neighbours. It is an approximation and
# is labelled as one on every record that uses it.
NOMINAL_FOOTPRINT_M = 400.0

# Above this, an outline is its authority's jurisdiction rather than the
# settlement's own extent. Sized from the data, not guessed: village and hamlet
# outlines run 0.52 km2 at the median and 3.74 km2 at the 95th percentile, and
# then jump straight to 277 km2. Fifteen sits in that gap — four times the 95th
# percentile — so it catches the 28 rows carrying a council polygon and no
# genuine village. Towns and cities are capped far higher because a real city
# is legitimately large; none in the table approaches its cap.
JURISDICTION_KM2 = {"village": 15.0, "hamlet": 15.0, "town": 150.0, "city": 300.0}
DEFAULT_JURISDICTION_KM2 = 150.0


def _is_jurisdiction(row) -> bool:
    """Whether this row's outline describes an authority rather than a place."""
    area = row["outline_km2"]
    if area is None:
        return False
    cap = JURISDICTION_KM2.get(row["place"] or "", DEFAULT_JURISDICTION_KM2)
    return float(area) > cap


def _nominal_footprint(row) -> dict[str, Any] | None:
    """A settlement whose outline belongs to its regional council, as a circle.

    Drawn around the town's own label point, which is the only position in the
    row that is actually about this town. `outline_basis` records that this is
    a nominal footprint so nothing downstream reports it as a surveyed
    boundary.
    """
    latitude, longitude = row["label_lat"], row["label_lon"]
    if latitude is None or longitude is None:
        return None

    import math

    lat_step = NOMINAL_FOOTPRINT_M / 111_320.0
    lon_step = lat_step / max(math.cos(math.radians(float(latitude))), 1e-6)
    ring = tuple(
        (
            float(longitude) + lon_step * math.sin(math.radians(angle)),
            float(latitude) + lat_step * math.cos(math.radians(angle)),
        )
        for angle in range(0, 360, 30)
    )

    return {
        "locality_id": row["town_id"],
        "name": row["name_en"] or row["name_he"],
        "name_he": row["name_he"],
        "population": row["population"],
        "place": row["place"],
        "authority": row["authority"],
        "authority_type": row["authority_type"],
        "authority_phone": row["authority_phone"],
        "authority_website": row["authority_website"],
        "fire_district": row["fire_district"],
        "police_station": row["police_station"],
        "outline_basis": "nominal_circle_around_label_point",
        "rings": (ring + (ring[0],),),
    }
