"""The fire spread analyser: one coordinator incident in, one forecast out.

Reads an incident exactly as `coordinator/incidents.py` stores it, grows the
fire with `spread.py`, asks `exposure.py` who is in the way, and states the
result in a sentence. No provider call and no model artefact: every number here
comes out of published fire physics applied to the environment it is handed, so
the same incident and the same weather always produce the same forecast.

Why the environment is an argument rather than something this fetches
--------------------------------------------------------------------
The weather, the cover fractions and the terrain all live in the store and
`repositories/surface.py` already aggregates them over a radius. Passing them
in anyway keeps the judgement separable from the retrieval: the hard part to
get right is what the numbers mean, and a function that reaches into Postgres
to find that out can only be tested against Postgres. `environment_for` is the
thin production loader; everything interesting is in `analyze`, which is pure.

Three semantics now share the words "risk" in this package and must not be
confused. `risk_prediction_agent` scores 0-1, the chance a fire *starts*.
`risk_analysis_agent` scores 0-100, how bad a fire that exists already is.
This scores 0-100 for something narrower again: how bad its *spread* is about
to be, over a stated horizon. Every consumer branches on `risk_semantics`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ecoguard.analyzers.emergency.fire.exposure import (
    BURNING,
    LIKELY,
    POSSIBLE,
    localities_at_risk,
    population_at_risk,
)
from ecoguard.analyzers.emergency.fire.spread import (
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


def _severity(behaviour: Mapping[str, Any], at_risk: Sequence[Mapping[str, Any]]) -> int:
    """A 0-100 spread severity, from the rate and from who it reaches."""
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
    return min(100, score)


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


def analyze(
    incident: Mapping[str, Any],
    environment: Mapping[str, Any],
    *,
    horizon_minutes: float = DEFAULT_HORIZON_MINUTES,
    localities: Sequence[Mapping[str, Any]] | None = None,
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
    origin = {
        "latitude": latitude,
        "longitude": longitude,
        "locality": next(
            (item["name"] for item in at_risk if item["exposure"] == BURNING), None
        ),
    }

    stalled = rings["status"] != "ok"
    score = None if stalled else _severity(behaviour, at_risk)
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
        "behaviour": {
            "head_ros_m_per_min": round(behaviour["head_ros_m_per_min"], 2),
            "back_ros_m_per_min": round(behaviour["back_ros_m_per_min"], 3),
            "heading_deg": rings.get("heading_deg"),
            "heading_compass": (
                None if stalled else compass_point(rings["heading_deg"])
            ),
            "length_to_width": round(behaviour["length_to_width"], 2),
            "effective_wind_kmh": round(behaviour["effective_wind_kmh"], 1),
            "fuel_model": behaviour["fuel"]["fuel_model_code"],
            "dominant_fuel": behaviour["fuel"]["dominant_fuel_model"],
            "burnable_fraction": behaviour["fuel"]["burnable_fraction"],
            "dead_fuel_moisture": round(float(dead_moisture), 4),
            "live_fuel_moisture": round(float(live_moisture), 4),
        },
        "spread": rings,
        "exposure": at_risk,
        "population_at_risk": population_at_risk(at_risk),
        "headline": _headline(origin, behaviour, rings, at_risk, horizon_minutes),
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


def _empty(incident_id: Any, status: str, reason: str) -> dict[str, Any]:
    """A result that made no assessment, and says so without implying safety."""
    return {
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
        "headline": None,
        "limits": LIMITS,
    }
