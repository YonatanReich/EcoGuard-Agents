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


class NamedTownMatch(BaseModel):
    """A text-named town related spatially to a structured signal point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    town_id: str
    name_he: str
    name_en: str
    place: str | None = None
    cbs_code: str | None = None
    outline_source: str | None = None
    authority: str | None = None
    authority_type: str | None = None
    distance_m: float = Field(ge=0)
    contains_signal: bool


class NamedTownLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: TownLookupStatus
    match: NamedTownMatch | None = None
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

_NAMED_TOWN_SQL = text(
    """
    WITH origin AS (
      SELECT ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326) AS point
    )
    SELECT
      town_id,
      name_he,
      name_en,
      place,
      cbs_code,
      outline_source,
      authority,
      authority_type,
      ST_Distance(outline, origin.point::geography) AS distance_m,
      ST_Covers(outline::geometry, origin.point) AS contains_signal
    FROM towns, origin
    WHERE name_he = ANY(CAST(:candidate_names AS text[]))
    ORDER BY
      array_position(CAST(:candidate_names AS text[]), name_he),
      distance_m,
      population DESC NULLS LAST,
      town_id
    LIMIT 1
    """
)


def resolve_named_town(
    *,
    candidate_names: list[str],
    latitude: float,
    longitude: float,
    session_factory=Session,
) -> NamedTownLookupResult:
    """Resolve explicit Hebrew locality names and relate their outline to a signal.

    The returned distance is from the authoritative town polygon, not its label
    point.  Label coordinates are deliberately not returned: a locality match
    is an area-level observation and must never masquerade as an event point.
    """
    names = list(dict.fromkeys(name.strip() for name in candidate_names if name.strip()))
    if not names:
        return NamedTownLookupResult(status=TownLookupStatus.SUCCESS_EMPTY)

    try:
        with session_factory() as session:
            if not session.execute(_TOWNS_EXISTS_SQL).scalar_one():
                return NamedTownLookupResult(
                    status=TownLookupStatus.REFERENCE_DATA_NOT_LOADED,
                    reason="reference_data_not_loaded",
                )
            if not session.execute(_TOWNS_POPULATED_SQL).scalar_one():
                return NamedTownLookupResult(
                    status=TownLookupStatus.REFERENCE_DATA_NOT_LOADED,
                    reason="reference_data_not_loaded",
                )
            row = session.execute(
                _NAMED_TOWN_SQL,
                {
                    "candidate_names": names,
                    "latitude": latitude,
                    "longitude": longitude,
                },
            ).mappings().first()
            match = NamedTownMatch.model_validate(dict(row)) if row else None
    except (SQLAlchemyError, ValidationError, TypeError, ValueError):
        return NamedTownLookupResult(
            status=TownLookupStatus.UNAVAILABLE,
            reason="town_repository_unavailable",
        )

    return NamedTownLookupResult(
        status=(
            TownLookupStatus.SUCCESS_WITH_RESULTS
            if match is not None
            else TownLookupStatus.SUCCESS_EMPTY
        ),
        match=match,
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
