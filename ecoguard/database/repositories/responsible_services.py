"""Which services answer for a place: the jurisdiction question.

Distinct from "which station is nearest", which `resource_allocator` answers by
road travel time. Both matter and they are not the same answer — the nearest
appliance may belong to another district, and who is *responsible* decides who
is notified, who commands, and who requests assistance from whom.

The district alias
------------------
`towns.fire_district` and `fire_stations.district` name the same seven
districts in two different ways, because they were loaded from two different
sources. One of them disagrees:

    towns:    דן  דרום  חוף  יו"ש            ירושלים  מרכז  צפון
    stations: דן  דרום  חוף  יהודה ושומרון   ירושלים  מרכז  צפון

A direct join therefore returns nothing for 122 towns — not an error, an empty
result, which reads exactly like "no station is responsible for this town". The
alias is resolved here rather than by editing either table, because both are
reference data reloaded from their own sources and an edit would be undone by
the next load.

`לא מסווג (OSM)` is the other unmatched value: three stations that came from
OpenStreetMap without a district. They are reachable by proximity and belong to
no jurisdiction we know, which is a different fact from belonging to none.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session

logger = logging.getLogger(__name__)

# Two spellings of one district. Maps the towns-table form to the
# stations-table form, which is the direction every lookup here needs.
DISTRICT_ALIASES = {
    'יו"ש': "יהודה ושומרון",
}

# Stations whose district is this carry no jurisdiction we can resolve. They
# are still dispatchable by proximity; they are simply not anybody's
# responsible station.
UNCLASSIFIED_DISTRICT = "לא מסווג (OSM)"


def district_for_stations(town_district: str | None) -> str | None:
    """The stations-table spelling of a town's fire district."""
    if not town_district:
        return None
    return DISTRICT_ALIASES.get(town_district, town_district)


def responsible_services(town_id: str) -> dict[str, Any]:
    """Who answers for one town: fire district, its stations, and the police.

    Returns the district as the town names it, the stations belonging to that
    district, and the police station resolved through `town_police_stations`
    rather than by matching names — that table carries a match confidence,
    and a name match alone resolved only 560 of 1,168 towns.

    A town whose district resolves to no stations comes back with an empty
    list and the district still named, so a caller can tell "no stations on
    file for this district" from "this town has no district".
    """
    stations_district = None
    with Session() as session:
        town = session.execute(
            text(
                """
                SELECT town_id, name_he, name_en, population, fire_district,
                       authority, authority_phone, authority_website
                FROM towns WHERE town_id = :town_id
                """
            ),
            {"town_id": town_id},
        ).mappings().first()
        if town is None:
            return {"town_id": town_id, "found": False}

        stations_district = district_for_stations(town["fire_district"])
        fire_stations = (
            session.execute(
                text(
                    """
                    SELECT id, name, address, regional,
                           ST_Y(location::geometry) AS latitude,
                           ST_X(location::geometry) AS longitude
                    FROM fire_stations
                    WHERE district = :district
                    ORDER BY regional DESC, name
                    """
                ),
                {"district": stations_district},
            ).mappings().all()
            if stations_district else []
        )

        police = session.execute(
            text(
                """
                SELECT p.id, p.name, p.address, tps.match_confidence,
                       ST_Y(p.location::geometry) AS latitude,
                       ST_X(p.location::geometry) AS longitude
                FROM town_police_stations tps
                JOIN police_stations p ON p.id = tps.police_station_id
                WHERE tps.town_id = :town_id
                ORDER BY tps.match_confidence DESC NULLS LAST
                """
            ),
            {"town_id": town_id},
        ).mappings().all()

    return {
        "town_id": town["town_id"],
        "found": True,
        "name": town["name_en"] or town["name_he"],
        "name_he": town["name_he"],
        "population": town["population"],
        "authority": town["authority"],
        "authority_phone": town["authority_phone"],
        "authority_website": town["authority_website"],
        "fire_district": town["fire_district"],
        "fire_stations": [dict(row) for row in fire_stations],
        "police_stations": [dict(row) for row in police],
    }


def district_station_coverage() -> list[dict[str, Any]]:
    """Towns and stations per district — the check that the alias is working.

    A district with towns and zero stations is the failure this module exists
    to prevent, and it is invisible in any single lookup.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT t.fire_district,
                       count(DISTINCT t.town_id) AS towns,
                       (SELECT count(*) FROM fire_stations f
                         WHERE f.district = CASE t.fire_district
                                              WHEN 'יו"ש' THEN 'יהודה ושומרון'
                                              ELSE t.fire_district END
                       ) AS stations
                FROM towns t
                WHERE t.fire_district IS NOT NULL
                GROUP BY t.fire_district
                ORDER BY t.fire_district
                """
            )
        ).mappings().all()
    return [dict(row) for row in rows]



# One statement, one round trip: the store is remote and each query costs a
# network hop (~150 ms), so six separate lookups took over a second.
#
# The town is the one whose outline covers the point — the smallest, since
# outlines overlap (a municipal boundary contains its neighbourhoods) — or,
# when none does, the nearest. A fire in open forest belongs to no settlement,
# but the nearest town's authority and police are still who the operator calls.
_RESPONSIBLE_PARTIES_SQL = text(
    """
    WITH pt AS (
        SELECT ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326) AS g
    ),
    covering AS (
        SELECT t.town_id, t.name_he, t.name_en, t.authority, t.authority_type,
               t.authority_phone, t.authority_address, t.authority_website,
               t.fire_district, 0::float AS distance_m
        FROM towns t, pt
        WHERE ST_Covers(t.outline, pt.g::geography)
        ORDER BY t.area_km2 ASC NULLS LAST, t.town_id
        LIMIT 1
    ),
    nearest AS (
        SELECT t.town_id, t.name_he, t.name_en, t.authority, t.authority_type,
               t.authority_phone, t.authority_address, t.authority_website,
               t.fire_district, ST_Distance(t.outline, pt.g::geography) AS distance_m
        FROM towns t, pt
        WHERE NOT EXISTS (SELECT 1 FROM covering)
        ORDER BY t.outline <-> pt.g::geography
        LIMIT 1
    ),
    town AS (SELECT * FROM covering UNION ALL SELECT * FROM nearest)
    SELECT
        (SELECT row_to_json(town) FROM town) AS town,
        (SELECT row_to_json(x) FROM (
            SELECT p.name, p.address, p.phone,
                   ST_Distance(p.location::geography, pt.g::geography) AS distance_m
            FROM town
            JOIN town_police_stations tps ON tps.town_id = town.town_id
            JOIN police_stations p ON p.id = tps.police_station_id, pt
            ORDER BY tps.match_confidence DESC NULLS LAST
            LIMIT 1) x) AS linked_police,
        (SELECT row_to_json(x) FROM (
            SELECT name, address, phone,
                   ST_Distance(location::geography, pt.g::geography) AS distance_m
            FROM police_stations, pt
            ORDER BY location::geometry <-> pt.g
            LIMIT 1) x) AS nearest_police,
        (SELECT row_to_json(x) FROM (
            SELECT name, address, tags->>'phone' AS phone,
                   ST_Distance(location::geography, pt.g::geography) AS distance_m
            FROM fire_stations, pt
            WHERE location IS NOT NULL
            ORDER BY location::geometry <-> pt.g
            LIMIT 1) x) AS nearest_fire,
        (SELECT row_to_json(x) FROM (
            SELECT name, address, NULL AS phone,
                   ST_Distance(location::geography, pt.g::geography) AS distance_m
            FROM mda_stations, pt
            WHERE location IS NOT NULL
            ORDER BY location::geometry <-> pt.g
            LIMIT 1) x) AS nearest_mda
    """
)


def _station(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "name": row["name"],
        "address": row["address"],
        "phone": row["phone"],
        "distance_m": round(row["distance_m"]) if row["distance_m"] is not None else None,
    }


def responsible_parties_at(*, latitude: float, longitude: float) -> dict[str, Any]:
    """Who to call about a point: authority, police, nearest fire and MDA.

    The authority and police are the *responsible* ones — the town at the point
    (see the SQL above) and that town's linked police station. Fire and MDA are
    simply the nearest by straight line; which crew actually goes is the
    allocator's road-time answer, not this one.

    `basis` says how the police station was reached, so the UI can tell "this
    town's police station" from "the nearest one, because the town has no link".
    """
    with Session() as session:
        row = session.execute(
            _RESPONSIBLE_PARTIES_SQL, {"latitude": latitude, "longitude": longitude},
        ).mappings().one()

    town = row["town"]
    authority = None
    if town is not None:
        authority = {
            "town_name_he": town["name_he"],
            "town_name_en": town["name_en"],
            "name": town["authority"],
            "type": town["authority_type"],
            "phone": town["authority_phone"],
            "address": town["authority_address"],
            "website": town["authority_website"],
            "fire_district": town["fire_district"],
            # 0 inside the outline; otherwise how far the point is from it.
            "distance_m": round(town["distance_m"] or 0),
        }

    police_station = _station(row["linked_police"] or row["nearest_police"])
    if police_station is not None:
        police_station["basis"] = "responsible" if row["linked_police"] else "nearest"

    return {
        "authority": authority,
        "police_station": police_station,
        "nearest_fire_station": _station(row["nearest_fire"]),
        "nearest_mda_station": _station(row["nearest_mda"]),
    }
