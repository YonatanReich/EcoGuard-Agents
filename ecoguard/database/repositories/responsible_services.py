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
