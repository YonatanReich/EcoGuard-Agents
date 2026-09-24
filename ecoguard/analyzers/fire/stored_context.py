"""The fire danger, weather and surroundings of an incident, read from the store.

The older single-point fire query built these three by calling three providers
while an operator waited. A coordinator incident has no such request to hang
off, so they used to be left empty - and an empty section does not read as
"nobody fetched this", it reads as "there is nothing there". Cards said no fire
danger was available for coordinates whose danger band was sitting in the
database, and named fires by latitude because no settlement had been looked up.

So they are read from what the collectors already stored. Same numbers, no
provider call, no wait, and repeatable long after the event.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

# The published bounds of each fire-danger band. The provider serves a band
# name rather than a number, and the assessment quotes the range so a reader
# can see how wide "very high" actually is.
FWI_BAND_RANGE: dict[str, tuple[float, float | None]] = {
    "low": (0.0, 11.2),
    "moderate": (11.2, 21.3),
    "high": (21.3, 38.0),
    "very_high": (38.0, 50.0),
    "extreme": (50.0, 70.0),
    "very_extreme": (70.0, None),
}

# How far out a settlement still counts as "near this fire" for the purpose of
# naming it. Wider than any plausible spread horizon, because the question here
# is what is around the fire, not what it will reach.
SETTLEMENT_RADIUS_M = 25_000.0

# How many settlements to carry. They arrive nearest-first, and the assessment
# renders the closest few - past a dozen the list stops informing a decision
# and starts padding the prompt.
MAX_SETTLEMENTS = 12


def fire_danger_from(environment: Mapping[str, Any] | None) -> dict[str, Any]:
    """The fire-danger band around the incident, in the shape the assessment reads.

    Reports a failed collection rather than an absent one when no band covers
    the coordinate, so the difference between "not dangerous" and "not known"
    survives into the assessment.
    """
    danger = (environment or {}).get("fire_danger") or {}
    level = danger.get("worst_level")
    if not level or not danger.get("cell_count"):
        return {
            "source": "GWIS/EFFIS fire weather index",
            "collection_status": "failed",
            "reason": "no_danger_band_stored_for_this_coordinate",
        }
    low, high = FWI_BAND_RANGE.get(str(level), (None, None))
    return {
        "source": "GWIS/EFFIS fire weather index",
        "collection_status": "success",
        "danger_class": str(level),
        "fwi": danger.get("fwi"),
        "fwi_min": low,
        "fwi_max": high,
        "cell_count": danger.get("cell_count"),
        "observed_at": danger.get("observed_at"),
    }


def weather_context_from(environment: Mapping[str, Any] | None) -> dict[str, Any]:
    """The weather at the incident's own hour, in the shape the assessment reads.

    Carries the reading's age, because an hour-old wind describes the fire and a
    six-hour-old one describes a different afternoon.
    """
    environment = environment or {}
    current = {
        key: environment[key]
        for key in (
            "temperature_c",
            "humidity_percent",
            "wind_speed_kmh",
            "wind_direction_deg",
        )
        if environment.get(key) is not None
    }
    if not current:
        return {
            "source": "Open-Meteo stored observations",
            "collection_status": "failed",
            "reason": "no_weather_reading_for_the_incident_hour",
            "current": {},
        }
    return {
        "source": "Open-Meteo stored observations",
        "collection_status": "success",
        "observed_at": environment.get("observed_at"),
        "current": current,
    }


def _distance_km(latitude: float, longitude: float, locality: Mapping[str, Any]) -> float:
    """Roughly how far a settlement is, for ordering the list nearest-first.

    Measured to the closest point on its outline that the store holds. Good
    enough to rank by, which is all it is used for - the store does not return
    a distance and asking for one costs a second query.
    """
    import math

    scale = math.cos(math.radians(latitude))
    best = math.inf
    for ring in locality.get("rings") or ():
        for point_lon, point_lat in ring:
            north = (point_lat - latitude) * 111.32
            east = (point_lon - longitude) * 111.32 * scale
            best = min(best, north * north + east * east)
    return math.sqrt(best) if best < math.inf else math.inf


def geospatial_context_at(
    latitude: float, longitude: float, *, localities: tuple[Mapping[str, Any], ...] = ()
) -> dict[str, Any]:
    """What is around the incident: settlements, and who answers for the place.

    Built from the towns and station tables rather than a live map query. The
    stored rows carry the population, the local authority's telephone number and
    the responsible police station on the same row, which the map service does
    not - so this is both faster and more useful than what it replaces.

    Returns an empty dict when nothing could be read, which the assessment reads
    as "never looked" rather than "nothing there".
    """
    # Nearest first. The store returns them in no particular order, and the
    # first one names the event on the map - so unsorted, a fire beside a town
    # of twenty thousand could be titled after a hamlet 20 km the other way.
    nearest = sorted(
        (item for item in localities if item.get("name") or item.get("name_he")),
        key=lambda item: _distance_km(latitude, longitude, item),
    )
    settlements = [
        {
            "name": item.get("name") or item.get("name_he"),
            "name_he": item.get("name_he"),
            "type": item.get("place"),
            "population": item.get("population"),
            "distance_km": round(_distance_km(latitude, longitude, item), 1),
            "authority": item.get("authority"),
            "authority_phone": item.get("authority_phone"),
            "fire_district": item.get("fire_district"),
            "police_station": item.get("police_station"),
        }
        for item in nearest[:MAX_SETTLEMENTS]
    ]

    try:
        from ecoguard.database.repositories.responsible_services import (
            responsible_parties_at,
        )

        parties = responsible_parties_at(latitude=latitude, longitude=longitude)
    except Exception:
        logger.exception("could not read who is responsible for the incident location")
        parties = {}

    def station(key: str) -> list[dict[str, Any]]:
        """One responsible station as a one-item list, or empty when there is none."""
        row = (parties or {}).get(key)
        if not isinstance(row, Mapping) or not row.get("name"):
            return []
        return [
            {
                "name": row.get("name"),
                "address": row.get("address"),
                "phone": row.get("phone"),
                "distance_m": row.get("distance_m"),
            }
        ]

    if not settlements and not parties:
        return {}

    return {
        "source": "EcoGuard reference data",
        "collection_status": "success",
        "search_radius_km": SETTLEMENT_RADIUS_M / 1000.0,
        "nearby_settlements": settlements,
        "nearby_fire_stations": station("nearest_fire_station"),
        "nearby_police_stations": station("police_station"),
        "nearby_hospitals": station("nearest_mda_station"),
        # Roads are not held as a national layer, so this stays empty rather
        # than claiming a search found none.
        "nearby_roads": [],
        "responsible_authority": (parties or {}).get("authority"),
    }


def stored_context_for(incident: Mapping[str, Any]) -> dict[str, Any]:
    """The three enrichments for one incident, each reporting its own failure.

    Never raises: a store that cannot be read produces sections that say so,
    because an incident with no surroundings is still worth assessing.
    """
    from ecoguard.analyzers.fire.environment import environment_for, localities_for

    latitude, longitude = incident.get("latitude"), incident.get("longitude")
    if latitude is None or longitude is None:
        return {
            "fire_danger": None,
            "weather_context": None,
            "geospatial_context": None,
        }

    try:
        environment = environment_for(incident)
    except Exception:
        logger.exception("could not read the environment around the incident")
        environment = None

    try:
        localities = localities_for(incident, radius_m=SETTLEMENT_RADIUS_M)
    except Exception:
        logger.exception("could not read settlements near the incident")
        localities = ()

    return {
        "fire_danger": fire_danger_from(environment),
        "weather_context": weather_context_from(environment),
        "geospatial_context": geospatial_context_at(
            float(latitude), float(longitude), localities=localities
        ),
    }
