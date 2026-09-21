"""Which stations are responsible, and how many teams: a jurisdiction answer.

What this does NOT do
---------------------
It does not choose routes, rank by travel time, or pick vehicles. That is the
resource allocator's work: it holds the Mapbox routing, it claims specific
units atomically, and it resolves contention between simultaneous incidents.

The planner answers a different question — *who is responsible* — and
responsibility is jurisdictional, not geometric. The nearest station is not
automatically the responsible one, and on the border cases it usually is not.
Mixing the two questions produced a version of this module that ranked by road
time, which quietly moved an allocator concern into the planner and would have
had the two components disagreeing about the same fire.

Proximity still appears here, but only as a tiebreak *within* the responsible
district, to identify which of that district's stations is the home station.
It is ordering, not routing, and it is labelled as such on the result.

Territoriality first

The ordering is the point. Each district handles and contains events in its own
sector, and a neighbouring district assists by exception — so the home station
is the nearest station *inside the district the fire is in*, which is often not
the nearest station outright. Ranking by proximity first and filtering by
district afterwards produces a different and wrong answer.

The parallel initial response
-----------------------------
At grade 3 and above, when the nearest station overall lies outside the
district, one initial response team is dispatched from it **at the same time**
as the home station's full complement — not after, and not because the home
station proved insufficient. It needs no approval from the national control
centre, which is notified for information only.

That is the part of this procedure most easily implemented wrong, because the
natural shape in code is a fallback: try the home district, and if short, reach
outside. That shape is a different procedure with a different timeline, and it
would delay the closest appliance to the fire behind a decision that the
procedure does not require anyone to make. It is modelled here as a separate,
concurrently issued request and labelled as such on the result.

The procedure bounds it at one team. It is not a licence to draw from every
neighbouring district.

Police are a dispatch output, not a courtesy
--------------------------------------------
In a civil emergency the localised evacuation decision belongs to Israel
Police, not to the Fire Authority. So for grade 3 and above — the grade defined
by a settlement being inside the footprint — the responsible police station for
each threatened locality is an actual notification target, and it comes from
the resolved `town_police_stations` join rather than from a name match.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.database.repositories.responsible_services import (
    district_for_stations,
)
from ecoguard.response_planner.fire.dispatch_policy import (
    CROSS_DISTRICT_GRADE,
    EXTREME_FIRE_WEATHER_SEVERITY,
    FORCE_COMPLETION,
    GRADES,
    IMMEDIATE_DISPATCH,
    INITIAL_RESPONSE_TEAMS_FROM_OUTSIDE,
    LIMITS,
    MULTIPLE_LOCALITIES,
    TEAMS_PER_STATION,
)

logger = logging.getLogger(__name__)


def derive_grade(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """The event grade, and the reason for it.

    Reads only what the analyser measured: which settlements the footprint
    reaches, how built-up the ground is, and the spread severity. Every grade
    carries the fact that raised it, so a dispatcher can disagree with the
    grade by disagreeing with the fact.
    """
    exposure: Sequence[Mapping[str, Any]] = analysis.get("exposure") or ()
    inside = [
        item for item in exposure
        if item.get("exposure") in {"burning", "likely"}
    ]
    severity = analysis.get("risk_score") or 0
    built_up = (analysis.get("behaviour") or {}).get("burnable_fraction")
    structures = [
        site for site in analysis.get("infrastructure_at_risk") or ()
        if site.get("exposure") in {"burning", "likely"}
    ]

    if not inside:
        # No settlement in the footprint. Structures still lift it above the
        # open-terrain floor: a fire reaching an industrial estate is not a
        # fire in empty scrub, even with nobody living there.
        grade = 2 if structures else 1
        reason = (
            f"{len(structures)} mapped site(s) in the footprint, no settlement"
            if structures else
            "open terrain; no settlement and no mapped site in the footprint"
        )
    elif len(inside) >= MULTIPLE_LOCALITIES or severity >= EXTREME_FIRE_WEATHER_SEVERITY:
        grade = 4
        reason = (
            f"{len(inside)} settlements in the footprint"
            if len(inside) >= MULTIPLE_LOCALITIES else
            f"settlement threatened with spread severity {severity}"
        )
    else:
        grade = 3
        reason = f"{inside[0].get('name')} lies inside the projected footprint"

    # Grade 5 is the national threshold, and it is the escalation module's
    # verdict rather than this one's: the criteria are published and belong
    # where they are cited.
    if analysis.get("national_event"):
        grade, reason = 5, "national-event criteria met (201.02.003 §2.1)"

    band = GRADES[grade]
    return {
        "grade": grade,
        "teams_required": band["teams"],
        "teams_minimum": band.get("teams_min", band["teams"]),
        "reason": reason,
        "trigger_definition": band["trigger"],
        "basis": band.get("basis"),
        "cross_district_permitted": band["cross_district"],
        "settlements_in_footprint": [item.get("name") for item in inside],
    }


def district_at(latitude: float, longitude: float) -> str | None:
    """Which fire district a point falls in, by point-in-polygon."""
    with Session() as session:
        return session.execute(
            text(
                """
                SELECT district FROM fire_districts
                WHERE ST_Intersects(
                        boundary,
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
                LIMIT 1
                """
            ),
            {"lat": latitude, "lon": longitude},
        ).scalar()


def stations_by_distance(
    latitude: float, longitude: float, *, limit: int = 25
) -> list[dict[str, Any]]:
    """Located stations nearest the fire, with their district.

    Straight-line ordering, used only to pick the home station from among the
    responsible district's own stations. How anything travels is the resource
    allocator's question, and it holds the routing.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT id, name, district, address, regional,
                       ST_Y(location::geometry) AS latitude,
                       ST_X(location::geometry) AS longitude,
                       ST_Distance(
                         location,
                         ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                       ) AS straight_line_m
                FROM fire_stations
                WHERE location IS NOT NULL
                ORDER BY location <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                LIMIT :limit
                """
            ),
            {"lat": latitude, "lon": longitude, "limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]


def _capacity(station: Mapping[str, Any]) -> int:
    """Teams this station may contribute without being stripped bare."""
    return TEAMS_PER_STATION[bool(station.get("regional"))]


def select_stations(
    analysis: Mapping[str, Any],
    grade: Mapping[str, Any],
) -> dict[str, Any]:
    """Which stations to call, how many teams from each, and under which request.

    Args:
        analysis: a `spread_analyzer` result.
        grade: a `derive_grade` result.
    Returns:
        dict with the home district, the selected stations, the parallel
        initial response if one applies, the police notification targets, and
        the shortfall if the teams could not be filled.
    """
    origin = analysis.get("origin") or {}
    latitude, longitude = origin.get("latitude"), origin.get("longitude")
    if latitude is None or longitude is None:
        return {"status": "skipped", "reason": "incident_has_no_position"}

    home_district = district_at(float(latitude), float(longitude))
    stations_district = district_for_stations(home_district)
    candidates = stations_by_distance(float(latitude), float(longitude))
    if not candidates:
        return {"status": "failed", "reason": "no_located_station_found"}

    # Ordering within the district, not routing. The allocator decides how
    # anything actually gets there.
    ranked_by = "straight_line_distance_within_district"

    in_district = [s for s in candidates if s["district"] == stations_district]
    outside = [s for s in candidates if s["district"] != stations_district]

    selected: list[dict[str, Any]] = []
    assigned = 0
    required = grade["teams_required"]

    # 3. The home station's full complement. Nearest *inside* the district.
    home = in_district[0] if in_district else None
    if home is not None:
        teams = min(_capacity(home), required)
        selected.append({
            **home, "teams": teams, "role": "home_station",
            "request_type": IMMEDIATE_DISPATCH,
            "reason": f"nearest station inside {home_district}",
        })
        assigned += teams

    # 4. In parallel, not as a fallback: one initial response team from the
    #    nearest station overall when that station is outside the district.
    initial_response = None
    if grade["cross_district_permitted"] and outside:
        nearest_overall = candidates[0]
        if nearest_overall["district"] != stations_district:
            initial_response = {
                **nearest_overall,
                "teams": INITIAL_RESPONSE_TEAMS_FROM_OUTSIDE,
                "role": "initial_response_out_of_district",
                "request_type": IMMEDIATE_DISPATCH,
                "dispatched": "in parallel with the home station, not after it",
                "approval": "none required; national control centre notified "
                            "for information only",
                "reason": (
                    f"nearest station overall and outside {home_district}"
                ),
            }
            selected.append(initial_response)
            assigned += INITIAL_RESPONSE_TEAMS_FROM_OUTSIDE

    # 5. Fill the remainder, preferring in-district, ascending travel time.
    already = {station["id"] for station in selected}
    for pool, label in ((in_district, "in_district"), (outside, "out_of_district")):
        for station in pool:
            if assigned >= required:
                break
            if station["id"] in already:
                continue
            if label == "out_of_district" and not grade["cross_district_permitted"]:
                continue
            teams = min(_capacity(station), required - assigned)
            selected.append({
                **station, "teams": teams, "role": f"force_completion_{label}",
                "request_type": FORCE_COMPLETION,
                "reason": f"{label.replace('_', ' ')}, next by {ranked_by}",
            })
            already.add(station["id"])
            assigned += teams

    return {
        "status": "ok",
        "home_district": home_district,
        "ranked_by": ranked_by,
        "teams_required": required,
        "teams_assigned": assigned,
        "teams_shortfall": max(0, required - assigned),
        "stations": selected,
        "initial_response_out_of_district": initial_response,
        "police_notifications": _police_targets(analysis, grade),
        "mda_notifications": _mda_targets(analysis, grade),
        "limits": list(LIMITS),
    }


def _police_targets(
    analysis: Mapping[str, Any], grade: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The police station responsible for each threatened locality.

    Grade 3 and above only, because grade 3 is defined by a settlement being
    in the footprint and the police hold the localised evacuation decision.
    Below that there is no evacuation question for them to hold.
    """
    if grade["grade"] < CROSS_DISTRICT_GRADE:
        return []

    locality_ids = [
        item.get("locality_id") for item in analysis.get("exposure") or ()
        if item.get("exposure") in {"burning", "likely"} and item.get("locality_id")
    ]
    if not locality_ids:
        return []

    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT t.name_en, t.name_he, p.name AS station, p.address,
                       tps.match_confidence
                FROM town_police_stations tps
                JOIN police_stations p ON p.id = tps.police_station_id
                JOIN towns t ON t.town_id = tps.town_id
                WHERE tps.town_id = ANY(:ids)
                ORDER BY tps.match_confidence DESC NULLS LAST
                """
            ),
            {"ids": [str(item) for item in locality_ids]},
        ).mappings().all()

    return [
        {
            "locality": row["name_en"] or row["name_he"],
            "police_station": row["station"],
            "address": row["address"],
            "match_confidence": row["match_confidence"],
            "why": "Israel Police hold the localised evacuation decision in a "
                   "civil emergency",
        }
        for row in rows
    ]


def plan_dispatch(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Grade the event and name the responsible services.

    The planner's whole dispatch answer: what grade, which fire stations are
    responsible and for how many teams, and which police and MDA stations
    answer for each threatened locality. Which vehicle goes where, and by which
    road, is the allocator's.
    """
    grade = derive_grade(analysis)
    selection = select_stations(analysis, grade)
    return {"grade": grade, **selection}


def _mda_targets(
    analysis: Mapping[str, Any], grade: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The MDA station answering for each threatened locality.

    Two ways a station becomes responsible, and the result says which. Only
    130 of 1,191 localities have an MDA station of their own, so for the rest
    responsibility falls to the nearest located station — which is a weaker
    claim than a station sited in the town, and is labelled `nearest` rather
    than presented as the same thing.

    Grade 3 and above, matching the police rule: below that there is no
    settlement in the footprint and nobody to treat.
    """
    if grade["grade"] < CROSS_DISTRICT_GRADE:
        return []

    localities = [
        item for item in analysis.get("exposure") or ()
        if item.get("exposure") in {"burning", "likely"} and item.get("locality_id")
    ]
    if not localities:
        return []

    targets: list[dict[str, Any]] = []
    with Session() as session:
        for item in localities:
            row = session.execute(
                text(
                    """
                    WITH town AS (
                      SELECT name_he, outline FROM towns WHERE town_id = :town_id
                    )
                    SELECT m.name, m.locality, m.address,
                           coalesce(m.locality = town.name_he, false)
                             AS in_locality,
                           round(ST_Distance(
                             m.location,
                             ST_Centroid(town.outline::geometry)::geography
                           )::numeric) AS distance_m
                    FROM mda_stations m, town
                    WHERE m.location IS NOT NULL
                    -- Two traps here, both silent.
                    --
                    -- `coalesce(... , false)`: 17 of 168 MDA stations have a
                    -- NULL locality, and Postgres sorts NULLs FIRST under
                    -- `ORDER BY <bool> DESC`. Without the coalesce, a station
                    -- with no locality at all outranked every real match and
                    -- every distance — Beit Oren was answered by a station
                    -- 35 km away and a Negev fire by one 178 km away.
                    --
                    -- Both sides of ST_Distance cast to geography, so the
                    -- comparison is in metres rather than in degrees.
                    ORDER BY coalesce(m.locality = town.name_he, false) DESC,
                             ST_Distance(
                               m.location,
                               ST_Centroid(town.outline::geometry)::geography
                             )
                    LIMIT 1
                    """
                ),
                {"town_id": str(item["locality_id"])},
            ).mappings().first()
            if row is None:
                continue
            targets.append({
                "locality": item.get("name"),
                "mda_station": row["name"],
                "station_locality": row["locality"],
                "address": row["address"],
                "basis": "station_in_locality" if row["in_locality"] else "nearest",
                "distance_m": float(row["distance_m"]) if row["distance_m"] else None,
                "why": "casualty treatment and medical evacuation for the "
                       "threatened locality",
            })
    return targets
