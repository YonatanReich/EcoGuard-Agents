"""How bad a fire's spread is about to be, over a stated horizon.

Distinct from the other two fire scores: this one is about the next few hours
rather than the fire as it stands, and it is reported on its own scale so the
three can never be confused."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ecoguard.analyzers.fire.exposure import (
    BURNING,
    LIKELY,
    POSSIBLE,
    localities_at_risk,
    locality_containing,
    population_at_risk,
)
from ecoguard.analyzers.fire import confirmation, infrastructure
from ecoguard.analyzers.fire.spread import (
    fine_dead_fuel_moisture,
    live_moisture_for_month,
    rate_of_spread,
    spread_rings,
)
from ecoguard.shared.schemas import risk_level_for_score

AGENT_NAME = "FireSpreadAnalyzer"
RISK_SEMANTICS = "fire_spread_forecast"

# Three hours is the window a duty officer is actually deciding over: long
# enough that the fire has gone somewhere, short enough that the wind forecast
# still means something and that nobody reads it as a prediction of the whole
# incident.
DEFAULT_HORIZON_MINUTES = 180.0

# The compass, for saying which way a fire is running in words rather than in
# degrees. Sixteen points, because "east-northeast" is a direction a person can
# picture and 067 degrees is not.
COMPASS = (
    "north", "north-northeast", "northeast", "east-northeast",
    "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest",
    "west", "west-northwest", "northwest", "north-northwest",
)

# The severity rubric, written out rather than tuned. Each clause is a claim
# about what makes a spreading fire worse, and a reader who disagrees with the
# assessment can point at the clause they disagree with.
RATE_BANDS = ((30.0, 75), (10.0, 55), (2.0, 30), (0.0, 10))
ALREADY_IN_A_TOWN = 25
ARRIVES_WITHIN_THE_HOUR = 15
LARGE_POPULATION_EXPOSED = 10
LARGE_POPULATION = 50_000
IMMINENT_MINUTES = 60.0

# Above this share of built-up cover, the report says so explicitly. A
# third is the wildland/urban interface the USFA triage doctrine is about;
# below it, buildings are scattered enough that the wildland model is the
# whole story.
BUILT_UP_NOTABLE = 0.33

# What else being in the path is worth. Counting residents alone cannot tell a
# fire at a fuel depot from the same fire at an empty beach, and those are not
# the same event. A hazard site changes the tactic; a life-safety site changes
# how early the evacuation decision has to be taken; economic loss is real and
# neither of those.
HAZARD_SITE_EXPOSED = 20
LIFE_SAFETY_SITE_EXPOSED = 15
ECONOMIC_SITE_EXPOSED = 5

# Detection confidence caps severity rather than adding to it. A 90-point
# spread forecast built on one doubtful pixel is a confident answer to a
# question nobody has established is being asked, and presenting it at full
# severity is how an operator ends up dispatching to a hot roof.
# `unassessed` does not cap. Not having weighed the evidence is not a reason to
# call the fire less severe — that would turn a missing field into an argument
# against the fire, which is the one inference this package refuses to make.
SEVERITY_CAP_BY_CONFIDENCE = {
    confirmation.CONFIRMED: 100,
    confirmation.PROBABLE: 100,
    confirmation.UNASSESSED: 100,
    confirmation.POSSIBLE: 60,
    confirmation.DOUBTFUL: 35,
}

# How the exposure classes and arrival times translate into what a settlement
# should be doing now. These are read off the forecast, not out of a protocol:
# `immediate` means the fire is in the town or the head reaches it within the
# hour, and that is a statement about the fire rather than a lawful order. The
# authority to order an evacuation, and the doctrine governing how, belong to
# the response planner and to the incident commander. This exists so neither
# of them has to re-derive who is closest to being overrun.
EVACUATE_NOW = "immediate"
PREPARE = "prepare"
STANDBY = "standby"

EVACUATION_RANK = {EVACUATE_NOW: 0, PREPARE: 1, STANDBY: 2}

EVACUATION_REASON = {
    EVACUATE_NOW: "the fire is in the built-up area or reaches it within the hour",
    PREPARE: "on the forecast wind the fire reaches it within the horizon",
    STANDBY: "only a wind shift within forecast error brings the fire here",
}


def compass_point(bearing_deg: float) -> str:
    """A bearing as one of sixteen named directions."""
    return COMPASS[int((float(bearing_deg) % 360.0) / 22.5 + 0.5) % 16]


def _duration(minutes: float) -> str:
    """A horizon in the unit a person would say it in."""
    minutes = float(minutes)
    if minutes < 90:
        return f"{minutes:.0f} minutes"
    hours = minutes / 60.0
    if abs(hours - round(hours)) < 0.05:
        whole = int(round(hours))
        return f"{whole} hour" if whole == 1 else f"{whole} hours"
    return f"{hours:.1f} hours"


def _severity(
    behaviour: Mapping[str, Any],
    at_risk: Sequence[Mapping[str, Any]],
    sites: Sequence[Mapping[str, Any]] = (),
    verdict: str | None = None,
) -> int:
    """A 0-100 spread severity: how fast, who it reaches, and what else is there.

    The last term is what makes a fire at a power station score above an
    identical fire on open ground. It is counted once per category rather than
    once per site: three industrial units in one estate are one estate, and
    letting a dense map outrank a hospital would be an artefact of how
    thoroughly the area happens to have been surveyed.
    """
    rate = float(behaviour.get("head_ros_m_per_min") or 0.0)
    score = next(points for threshold, points in RATE_BANDS if rate >= threshold)

    if any(item["exposure"] == BURNING for item in at_risk):
        score += ALREADY_IN_A_TOWN
    if any(
        item["exposure"] == LIKELY
        and item["arrival_minutes"] is not None
        and item["arrival_minutes"] <= IMMINENT_MINUTES
        for item in at_risk
    ):
        score += ARRIVES_WITHIN_THE_HOUR
    # Only the population the fire is forecast to *reach*. Counting the
    # locality it started in would score every fire inside a city as though the
    # whole city were in its path, which is both wrong and unresponsive to the
    # one thing this analyser exists to answer — whether it is going anywhere.
    # Being inside a built-up area is already scored, once, above.
    if population_at_risk(at_risk)[LIKELY] >= LARGE_POPULATION:
        score += LARGE_POPULATION_EXPOSED

    categories = {site["category"] for site in sites}
    if infrastructure.HAZARD in categories:
        score += HAZARD_SITE_EXPOSED
    if infrastructure.LIFE_SAFETY in categories:
        score += LIFE_SAFETY_SITE_EXPOSED
    if infrastructure.ECONOMIC in categories:
        score += ECONOMIC_SITE_EXPOSED

    score = min(100, score)
    if verdict is not None:
        score = min(score, SEVERITY_CAP_BY_CONFIDENCE[verdict])
    return score


def _headline(
    origin: Mapping[str, Any],
    behaviour: Mapping[str, Any],
    rings: Mapping[str, Any],
    at_risk: Sequence[Mapping[str, Any]],
    horizon_minutes: float,
) -> str:
    """The forecast as one paragraph, built by template rather than generated.

    Deterministic on purpose. This sentence is the thing an operator reads and
    the thing the regression suite checks, so it must say exactly what the
    numbers say and nothing that was not computed. The language layer takes
    this as ground truth and may reorder or expand it; it may not introduce a
    place or a figure that is not already here.
    """
    where = origin.get("locality") or "open ground"

    if rings.get("status") != "ok":
        reason = {
            "no_burnable_fuel": "there is no continuous wildland fuel at the location",
            "fuel_above_moisture_of_extinction": (
                "the fuel is too wet to carry fire in the current conditions"
            ),
        }.get(rings.get("reason"), "conditions do not support spread")
        return (
            f"Fire reported in {where}. No wildland spread is forecast: {reason}. "
            "This is not an assessment of the fire itself, only of its ability "
            "to run through the surrounding fuel."
        )

    rate = float(behaviour["head_ros_m_per_min"])
    direction = compass_point(rings["heading_deg"])
    distance_km = rings["head_distance_m"] / 1000.0
    burning = [item for item in at_risk if item["exposure"] == BURNING]
    likely = [item for item in at_risk if item["exposure"] == LIKELY]
    possible = [item for item in at_risk if item["exposure"] == POSSIBLE]

    if burning:
        opening = f"Fire burning in {burning[0]['name']}"
    else:
        opening = f"Fire burning in {where}"

    parts = [
        f"{opening}, spreading {direction} at about {rate:.0f} m/min. "
        f"Unchecked, the head reaches roughly {distance_km:.1f} km "
        f"in {_duration(horizon_minutes)}."
    ]

    if likely:
        described = ", ".join(
            f"{item['name']} (population {item['population']:,})"
            + (
                f", about {item['arrival_minutes']:.0f} minutes away"
                if item["arrival_minutes"] is not None
                else ""
            )
            for item in likely
        )
        parts.append(f"On the forecast wind it reaches {described}.")
    if possible:
        parts.append(
            "If the wind shifts within forecast error it could also reach "
            + ", ".join(item["name"] for item in possible)
            + "."
        )
    if not likely and not possible:
        parts.append("No populated locality lies in the forecast path.")

    return " ".join(parts)


def evacuation_priorities(
    at_risk: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Which settlements to move, in what order, and who to ring about it.

    Derived entirely from exposure and arrival time — see the constants above
    for why that is a statement about the fire rather than an order to anybody.
    Every entry carries the local authority's telephone number where the towns
    table has one, because the gap between "Yokneam is 40 minutes away" and
    somebody picking up a phone is the whole point of this analyser.

    A settlement the fire is already inside is listed first and without an
    arrival time; putting a countdown on a place that is already burning reads
    as though there were still time to prepare.
    """
    priorities = []
    for item in at_risk:
        arrival = item.get("arrival_minutes")
        if item["exposure"] == BURNING:
            priority = EVACUATE_NOW
        elif item["exposure"] == LIKELY:
            priority = (
                EVACUATE_NOW
                if arrival is not None and arrival <= IMMINENT_MINUTES
                else PREPARE
            )
        else:
            priority = STANDBY

        priorities.append({
            "locality_id": item.get("locality_id"),
            "name": item.get("name"),
            "name_he": item.get("name_he"),
            "population": item.get("population"),
            "priority": priority,
            "reason": EVACUATION_REASON[priority],
            "arrival_minutes": arrival,
            "distance_m": item.get("distance_m"),
            # Absent rather than blank when the towns table has no number for
            # this authority: a caller must be able to tell "we do not have it"
            # from "there isn't one".
            "authority": item.get("authority"),
            "authority_phone": item.get("authority_phone"),
            "authority_website": item.get("authority_website"),
            "fire_district": item.get("fire_district"),
            "police_station": item.get("police_station"),
        })

    priorities.sort(
        key=lambda item: (
            EVACUATION_RANK[item["priority"]],
            item["arrival_minutes"] if item["arrival_minutes"] is not None else -1.0,
            -(item["population"] or 0),
        )
    )
    return priorities


def _people(count: Any) -> str:
    """A population as a person would say it, or an honest absence."""
    if count is None:
        return "an unknown number of people"
    count = int(count)
    return "1 person" if count == 1 else f"{count:,} people"


def build_report(
    origin: Mapping[str, Any],
    behaviour: Mapping[str, Any],
    rings: Mapping[str, Any],
    at_risk: Sequence[Mapping[str, Any]],
    evacuations: Sequence[Mapping[str, Any]],
    environment: Mapping[str, Any],
    ring_population: Mapping[str, Any] | None,
    score: int | None,
    horizon_minutes: float,
    *,
    detection: Mapping[str, Any] | None = None,
    sites: Sequence[Mapping[str, Any]] = (),
    history: Mapping[str, Any] | None = None,
) -> str:
    """The incident report, as sections a duty officer reads top to bottom.

    Built by template, for the same reason `_headline` is: this is the text an
    operator acts on and the text the regression suite checks, so every figure
    in it has to be one that was computed. The language layer downstream may
    reorder this or expand it; it may not introduce a place, a number or a
    recommendation that is not already here.

    Sections with nothing behind them say so rather than being dropped. "No
    populated locality lies in the forecast path" is an answer; a missing
    section is indistinguishable from a bug.
    """
    where = origin.get("locality") or "open ground"
    lines: list[str] = []

    # --- is this real ------------------------------------------------------
    # First, because everything below is conditional on it. A reader who takes
    # the evacuation list on trust without seeing that the detection is one
    # doubtful pixel has been misled by the ordering alone.
    if detection is not None:
        lines.append("DETECTION")
        lines.append(confirmation.statement(detection))
        lines.append("")

    # --- what is happening -------------------------------------------------
    lines.append("SITUATION")
    if rings.get("status") != "ok":
        reason = {
            "no_burnable_fuel": "there is no continuous wildland fuel at the location",
            "fuel_above_moisture_of_extinction": (
                "the fuel is too wet to carry fire in the current conditions"
            ),
        }.get(rings.get("reason"), "conditions do not support wildland spread")
        residents = origin.get("locality_population")
        who = (
            f" {where} has {residents:,} residents." if residents else ""
        )
        contact = origin.get("authority_phone")
        if contact:
            who += f" Local authority: {contact}."
        lines.append(
            f"Fire reported in {where}.{who} No wildland spread is forecast: {reason}. "
            "This assesses the ground's ability to carry fire, not the fire "
            "itself — a structure or vehicle fire here is unaffected by this "
            "finding and may still be serious."
        )
        lines.append("")
        lines.append("LIMITS")
        lines.extend(f"- {limit}" for limit in LIMITS)
        return "\n".join(lines)

    rate = float(behaviour["head_ros_m_per_min"])
    direction = compass_point(rings["heading_deg"])
    distance_km = rings["head_distance_m"] / 1000.0
    fuel = behaviour.get("dominant_fuel") or behaviour.get("fuel_model") or "mixed fuel"

    situation = (
        f"Fire burning in {where}, running {direction} at about {rate:.0f} m/min "
        f"through {str(fuel).replace('_', ' ')}."
    )
    wind = environment.get("wind_speed_kmh")
    if wind is not None:
        situation += (
            f" Wind {wind:.0f} km/h from "
            f"{compass_point(float(environment.get('wind_direction_deg') or 0.0))}"
        )
        temperature = environment.get("temperature_c")
        humidity = environment.get("humidity_percent")
        if temperature is not None and humidity is not None:
            situation += f", {temperature:.0f} C, {humidity:.0f}% humidity"
        situation += "."
    lines.append(situation)

    # The wildland fuel model deliberately ignores buildings — `fuel_models.py`
    # excludes built-up cover because a town burns as a structure fire with
    # different physics. That makes "spreading through shrubland" true and
    # badly incomplete on ground that is four-fifths houses, so the built-up
    # share is stated whenever it is the thing a reader would otherwise miss.
    built_up = environment.get("built_up_fraction")
    if built_up is not None and built_up >= BUILT_UP_NOTABLE:
        lines.append(
            f"{built_up * 100:.0f}% of this ground is built up. The spread "
            "forecast below covers wildland fuel only; fire in the structures "
            "themselves behaves differently and is not modelled here."
        )

    slope = environment.get("slope_deg")
    steepest = environment.get("slope_max_deg")
    if slope is not None:
        terrain = f"Ground averages {slope:.0f} degrees"
        if steepest is not None and steepest - slope >= 5:
            terrain += (
                f", with faces up to {steepest:.0f} degrees inside the same ground "
                "— a fire on one of those runs far faster than the average suggests"
            )
        lines.append(terrain + ".")

    if history:
        previous = history.get("fires_within_5km_previous_30d")
        yearly = history.get("fires_within_25km_previous_365d")
        if yearly:
            since = history.get("days_since_previous_detection_within_10km")
            sentence = (
                f"This area has burned before: {yearly} detections within "
                f"25 km in the past year"
            )
            if previous:
                sentence += f", {previous} of them within 5 km in the past month"
            if since is not None:
                sentence += f"; the last within 10 km was {since:.0f} days ago"
            lines.append(sentence + ".")

    # --- where it goes -----------------------------------------------------
    lines.append("")
    lines.append("FORECAST SPREAD")
    lines.append(
        f"Unchecked, the head reaches roughly {distance_km:.1f} km "
        f"{direction} in {_duration(horizon_minutes)}. Two extents are drawn: "
        "the likely one on the forecast wind, and a wider possible one "
        "covering a wind shift within forecast error."
    )

    # --- who is in it ------------------------------------------------------
    lines.append("")
    lines.append("PEOPLE AT RISK")
    totals = population_at_risk(at_risk)
    if ring_population is not None:
        lines.append(
            f"Inside the forecast spread: {_people(ring_population.get('people'))}, "
            "counted off the population grid over the drawn extent."
        )
    else:
        lines.append(
            "The population inside the drawn extent could not be counted "
            "— the population grid is unavailable. This is not a count of zero."
        )
    if totals[BURNING] or totals[LIKELY] or totals[POSSIBLE]:
        lines.append(
            "Whole-settlement totals, which count every resident of an affected "
            f"place rather than only those inside the line: "
            f"{totals[BURNING]:,} in settlements already burning, "
            f"{totals[LIKELY]:,} in settlements the forecast reaches, "
            f"{totals[POSSIBLE]:,} in settlements only a wind shift reaches."
        )

    # --- named places ------------------------------------------------------
    lines.append("")
    lines.append("SETTLEMENTS IN THE PATH")
    if not at_risk:
        lines.append("No populated locality lies in the forecast path.")
    for item in at_risk:
        parts = [f"- {item['name']}"]
        if item.get("population") is not None:
            parts.append(f"({item['population']:,})")
        if item["exposure"] == BURNING:
            parts.append("— fire is inside the built-up area")
        elif item["exposure"] == LIKELY:
            when = (
                f"about {item['arrival_minutes']:.0f} minutes away"
                if item.get("arrival_minutes") is not None
                else "within the horizon"
            )
            parts.append(f"— on the forecast wind, {when}")
        else:
            parts.append("— reachable only if the wind shifts within forecast error")
        if item.get("distance_m") is not None:
            parts.append(f"[{item['distance_m'] / 1000.0:.1f} km]")
        lines.append(" ".join(parts))

    # --- what else is in the way -------------------------------------------
    lines.append("")
    lines.append("OTHER SITES IN THE PATH")
    if not sites:
        lines.append(
            "No mapped hospital, school, industrial or hazardous site lies in "
            "the forecast path. This is what the survey holds, not proof that "
            "there is nothing there."
        )
    for site in sites[:12]:
        arrival = (
            "on the forecast wind" if site.get("exposure") == LIKELY
            else "only if the wind shifts"
        )
        # Read defensively: a site list assembled by a caller rather than by
        # `sites_at_risk` may be missing the geometry fields, and one odd
        # record must not take the whole report down with it.
        distance = site.get("distance_m")
        how_far = "" if distance is None else f" — {distance / 1000.0:.1f} km,"
        lines.append(
            f"- [{str(site.get('category', 'site')).replace('_', ' ')}] "
            f"{site.get('name') or site.get('kind') or 'unnamed site'} "
            f"({site.get('kind', 'site')}){how_far} {arrival}"
        )
    if len(sites) > 12:
        lines.append(f"  ...and {len(sites) - 12} more.")

    # --- what to do about it ----------------------------------------------
    lines.append("")
    lines.append("EVACUATION PRIORITY")
    if not evacuations:
        lines.append("No settlement is exposed; no evacuation follows from this forecast.")
    for item in evacuations:
        head = f"- {item['priority'].upper()}: {item['name']}"
        if item.get("population") is not None:
            head += f", {_people(item['population'])}"
        lines.append(f"{head} — {item['reason']}.")
        contacts = []
        if item.get("authority_phone"):
            contacts.append(f"authority {item['authority_phone']}")
        if item.get("fire_district"):
            contacts.append(f"fire district {item['fire_district']}")
        if item.get("police_station"):
            contacts.append(f"police {item['police_station']}")
        if contacts:
            lines.append("    " + "; ".join(contacts))
        else:
            lines.append("    no contact details on file for this authority")

    # --- how bad ------------------------------------------------------------
    lines.append("")
    lines.append("SEVERITY")
    if score is None:
        lines.append(
            "Not scored. This is an absence of assessment, not a low score."
        )
    else:
        lines.append(
            f"{risk_level_for_score(score)} — {score} of 100, for the spread over "
            f"the next {_duration(horizon_minutes)}. This scores how bad the "
            "spread is about to be; it is not how likely a fire was to start "
            "here, nor how severe the fire already is."
        )
        drivers = []
        if rate >= 30:
            drivers.append(f"a head rate of {rate:.0f} m/min")
        elif rate >= 10:
            drivers.append(f"a moderate head rate of {rate:.0f} m/min")
        if any(item["exposure"] == BURNING for item in at_risk):
            drivers.append("fire already inside a built-up area")
        imminent = [
            item for item in at_risk
            if item["exposure"] == LIKELY
            and item.get("arrival_minutes") is not None
            and item["arrival_minutes"] <= IMMINENT_MINUTES
        ]
        if imminent:
            drivers.append(f"{imminent[0]['name']} reached within the hour")
        if totals[LIKELY] >= LARGE_POPULATION:
            drivers.append(f"{totals[LIKELY]:,} people in settlements on the forecast path")
        categories = {site["category"] for site in sites}
        if infrastructure.HAZARD in categories:
            worst = next(s for s in sites if s["category"] == infrastructure.HAZARD)
            drivers.append(f"a hazardous site in the path ({worst['kind']})")
        if infrastructure.LIFE_SAFETY in categories:
            worst = next(s for s in sites if s["category"] == infrastructure.LIFE_SAFETY)
            drivers.append(f"a site whose occupants cannot self-evacuate ({worst['kind']})")
        if detection is not None and detection["verdict"] in (
            confirmation.POSSIBLE, confirmation.DOUBTFUL
        ):
            drivers.append(
                f"capped at {SEVERITY_CAP_BY_CONFIDENCE[detection['verdict']]} "
                f"because the detection is only {detection['verdict']}"
            )
        if drivers:
            lines.append("Driven by: " + "; ".join(drivers) + ".")

    gaps = list(environment.get("gaps") or ())
    if gaps:
        lines.append("")
        lines.append("EVIDENCE GAPS")
        lines.extend(f"- {gap.replace('_', ' ')}" for gap in gaps)

    lines.append("")
    lines.append("LIMITS")
    lines.extend(f"- {limit}" for limit in LIMITS)

    return "\n".join(lines)


def analyze(
    incident: Mapping[str, Any],
    environment: Mapping[str, Any],
    *,
    horizon_minutes: float = DEFAULT_HORIZON_MINUTES,
    localities: Sequence[Mapping[str, Any]] | None = None,
    ring_population: Mapping[str, Any] | None = None,
    sites: Sequence[Mapping[str, Any]] | None = None,
    fire_history: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Forecast where one incident's fire goes, and who that puts at risk.

    Args:
        incident: a coordinator incident. Only `id`, `latitude`, `longitude`
            and `primary_hazard` are read, so a partially populated record
            from a replay or a fixture works unchanged.
        environment: `temperature_c`, `humidity_percent`, `wind_speed_kmh`,
            `wind_direction_deg` (meteorological — the bearing the wind comes
            *from*), `cover_fractions`, `slope_deg`, `aspect_deg`. Optional
            `dead_fuel_moisture` and `live_fuel_moisture` override the values
            otherwise derived from the weather and the calendar.
        horizon_minutes: how far ahead to grow the fire.
        environment: conditions to assess against, instead of reading the
            store. Terrain, fuel, settlements and population are still read
            from the store either way.
        localities: outlines to test exposure against; defaults to the
            reference file.

    Returns:
        dict: the forecast. `status` is "skipped" when the incident is not a
        fire or has no usable position, "stalled" when the ground cannot carry
        fire, and "ok" otherwise. A skipped or stalled result carries
        `risk_score: None` — not zero. A fire that cannot spread through
        vegetation is not a fire that is harmless, and this analyser has no
        opinion on the structure it may be burning down.
    """
    incident_id = incident.get("id")
    if (incident.get("primary_hazard") or "fire") != "fire":
        return _empty(incident_id, "skipped", "not_a_fire_incident")

    latitude, longitude = incident.get("latitude"), incident.get("longitude")
    if latitude is None or longitude is None:
        return _empty(incident_id, "skipped", "incident_has_no_position")

    latitude, longitude = float(latitude), float(longitude)
    cover = dict(environment.get("cover_fractions") or {})
    if not cover:
        return _empty(incident_id, "skipped", "no_land_cover_for_location")

    observed_at = _observed_at(incident)
    dead_moisture = environment.get("dead_fuel_moisture")
    if dead_moisture is None:
        dead_moisture = fine_dead_fuel_moisture(
            float(environment.get("temperature_c", 25.0)),
            float(environment.get("humidity_percent", 50.0)),
        )
    live_moisture = environment.get("live_fuel_moisture")
    if live_moisture is None:
        live_moisture = live_moisture_for_month(observed_at.month)

    behaviour = rate_of_spread(
        cover,
        dead_fuel_moisture=float(dead_moisture),
        wind_speed_kmh=float(environment.get("wind_speed_kmh", 0.0)),
        slope_deg=float(environment.get("slope_deg", 0.0) or 0.0),
        live_fuel_moisture=float(live_moisture),
    )
    rings = spread_rings(
        latitude,
        longitude,
        behaviour,
        wind_direction_deg=float(environment.get("wind_direction_deg", 0.0)),
        aspect_deg=environment.get("aspect_deg"),
        horizon_minutes=horizon_minutes,
    )

    at_risk = localities_at_risk(latitude, longitude, rings, localities=localities)

    # Where the fire is, asked independently of where it is going. A structure
    # fire produces no rings, so nothing overlaps anything and the exposure
    # list is empty — but the address is still in a town, and reporting "open
    # ground" about a block of flats in Petah Tikva is the kind of wrong that
    # destroys trust in everything else on the page.
    containing = locality_containing(latitude, longitude, localities=localities)
    origin = {
        "latitude": latitude,
        "longitude": longitude,
        "locality": (containing or {}).get("name"),
        "locality_population": (containing or {}).get("population"),
        "authority": (containing or {}).get("authority"),
        "authority_phone": (containing or {}).get("authority_phone"),
        "fire_district": (containing or {}).get("fire_district"),
        "police_station": (containing or {}).get("police_station"),
    }

    # Is this a fire at all? Asked before anything is claimed about where it
    # is going, and carried onto the result either way.
    detection = confirmation.assess(incident, history=fire_history)

    exposed_sites = (
        list(sites) if sites is not None
        else infrastructure.sites_at_risk(latitude, longitude, rings)
    )

    stalled = rings["status"] != "ok"
    score = (
        None if stalled
        else _severity(behaviour, at_risk, exposed_sites, detection["verdict"])
    )
    evacuations = [] if stalled else evacuation_priorities(at_risk)

    # Built once and used twice — in the result and in the report — so the
    # prose and the structured fields can never disagree about a figure.
    behaviour_summary = {
        "head_ros_m_per_min": round(behaviour["head_ros_m_per_min"], 2),
        "back_ros_m_per_min": round(behaviour["back_ros_m_per_min"], 3),
        "heading_deg": rings.get("heading_deg"),
        "heading_compass": None if stalled else compass_point(rings["heading_deg"]),
        "length_to_width": round(behaviour["length_to_width"], 2),
        "effective_wind_kmh": round(behaviour["effective_wind_kmh"], 1),
        "fuel_model": behaviour["fuel"]["fuel_model_code"],
        "dominant_fuel": behaviour["fuel"]["dominant_fuel_model"],
        "burnable_fraction": behaviour["fuel"]["burnable_fraction"],
        "dead_fuel_moisture": round(float(dead_moisture), 4),
        "live_fuel_moisture": round(float(live_moisture), 4),
    }
    return {
        "agent": AGENT_NAME,
        "status": "stalled" if stalled else "ok",
        "reason": rings.get("reason"),
        "incident_id": incident_id,
        "risk_semantics": RISK_SEMANTICS,
        "risk_score": score,
        "risk_level": risk_level_for_score(score),
        "horizon_minutes": horizon_minutes,
        "assessed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "origin": origin,
        "behaviour": behaviour_summary,
        "spread": rings,
        "exposure": at_risk,
        "population_at_risk": population_at_risk(at_risk),
        # Residents inside the drawn extent, which is a different question from
        # the whole-settlement totals above. None means it was not counted, and
        # must never be read as none.
        "population_in_spread": dict(ring_population) if ring_population else None,
        "evacuation": evacuations,
        "detection": detection,
        "infrastructure_at_risk": exposed_sites,
        "infrastructure_summary": infrastructure.summarise(exposed_sites),
        "fire_history": dict(fire_history) if fire_history else None,
        "headline": _headline(origin, behaviour, rings, at_risk, horizon_minutes),
        "report": build_report(
            origin, behaviour_summary, rings, at_risk, evacuations,
            environment, ring_population, score, horizon_minutes,
            detection=detection, sites=exposed_sites, history=fire_history,
        ),
        "limits": LIMITS,
    }


# Stated on every result rather than in the documentation, because the result
# is what gets forwarded and the documentation is what stays behind.
LIMITS = (
    "Unsuppressed spread: no crew, engine, aircraft or existing containment is modelled.",
    "Surface fire only: spotting ahead of the front and sustained crown runs are not modelled.",
    "Barriers finer than the land-cover grid — a road, a firebreak, a wadi — are invisible here.",
    "Arrival times assume the forecast wind holds for the whole horizon.",
)


def _observed_at(incident: Mapping[str, Any]) -> datetime:
    """When the incident is happening, for the seasonal live-fuel switch."""
    for key in ("last_signal_at", "first_seen_at"):
        value = incident.get(key)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                    timezone.utc
                )
            except ValueError:
                continue
    return datetime.now(timezone.utc)


# What each non-assessment means, in a sentence an operator can act on. A
# skipped result used to carry `report: None`, which put a blank page in front
# of somebody holding a fire — the one failure this module's honest-absence
# design exists to prevent, reintroduced at the last step. Absence has to be
# legible, not merely truthful.
SKIP_EXPLANATION = {
    "not_a_fire_incident": (
        "This incident is not a fire, so no fire spread was forecast."
    ),
    "incident_has_no_position": (
        "This incident has no usable position, so no spread could be forecast. "
        "The detection exists; the coordinate does not."
    ),
    "no_land_cover_for_location": (
        "No land-cover data covers this location, so wildland spread cannot be "
        "modelled here. The location is water, bare ground the survey does not "
        "map, or outside the loaded grid. This says nothing about the fire "
        "itself — a structure, vehicle or industrial fire here is unaffected "
        "by this finding and may be serious."
    ),
    "environment_unavailable": (
        "The weather, terrain and fuel around this incident could not be read, "
        "so no spread was forecast. This is a data outage, not an all-clear."
    ),
}


def _empty(incident_id: Any, status: str, reason: str) -> dict[str, Any]:
    """A result that made no assessment, and says so without implying safety."""
    explanation = SKIP_EXPLANATION.get(
        reason, "This incident could not be assessed for fire spread."
    )
    report = "\n".join([
        "SITUATION",
        explanation,
        "",
        "SEVERITY",
        "Not scored. This is an absence of assessment, not a low score.",
        "",
        "LIMITS",
        *(f"- {limit}" for limit in LIMITS),
    ])
    return {
        "report": report,
        "agent": AGENT_NAME,
        "status": status,
        "reason": reason,
        "incident_id": incident_id,
        "risk_semantics": RISK_SEMANTICS,
        "risk_score": None,
        "risk_level": None,
        "origin": None,
        "behaviour": None,
        "spread": None,
        "exposure": [],
        "population_at_risk": {BURNING: 0, LIKELY: 0, POSSIBLE: 0},
        "population_in_spread": None,
        "evacuation": [],
        "headline": explanation,
        "limits": LIMITS,
    }


def analyze_incident(
    incident: Mapping[str, Any],
    *,
    horizon_minutes: float = DEFAULT_HORIZON_MINUTES,
    environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The production entry point: a coordinator incident in, a report out.

    Everything that touches the store happens here, in three reads, and the
    judgement stays in `analyze` where it can be tested without a database.
    That split is the one this module's docstring has always described.

    Args:
        incident: a coordinator incident, as `coordinator/incidents.py` stores
            it. Needs `id`, `latitude`, `longitude` and `primary_hazard`.
        horizon_minutes: how far ahead to grow the fire.
        environment: conditions to assess against, instead of reading the
            store. Terrain, fuel, settlements and population are still read
            from the store either way.

    Returns:
        The same shape `analyze` returns. A read that fails degrades to a
        skipped result naming the reason rather than to a forecast built on
        defaults — a fire modelled on weather it is not having is not a
        conservative estimate.
    """
    from ecoguard.analyzers.fire.environment import (
        environment_for,
        history_for,
        localities_for,
        population_within,
    )

    incident_id = incident.get("id")
    if (incident.get("primary_hazard") or "fire") != "fire":
        return _empty(incident_id, "skipped", "not_a_fire_incident")

    # A supplied environment is how a drill or a replay states the conditions
    # it is about. Everything else — terrain, fuel, settlements, population —
    # still comes from the store, so only the weather is hypothetical and the
    # ground the fire runs over is real.
    if environment is None:
        environment = environment_for(incident)
    if environment is None:
        return _empty(incident_id, "skipped", "environment_unavailable")

    # The rings are needed before the population inside them can be counted, so
    # this runs twice: once to get the geometry, once with the count folded in
    # so the report can state it. The second pass is pure arithmetic on data
    # already in hand — no provider call, no second read of the store.
    localities = localities_for(incident)
    history = history_for(incident)
    first = analyze(
        incident, environment,
        horizon_minutes=horizon_minutes, localities=localities,
        fire_history=history,
    )
    if first["status"] != "ok":
        return first

    ring_population = population_within((first["spread"] or {}).get("likely") or [])
    return analyze(
        incident, environment,
        horizon_minutes=horizon_minutes, localities=localities,
        ring_population=ring_population, fire_history=history,
    )
