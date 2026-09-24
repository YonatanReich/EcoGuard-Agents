"""The conditions around a fire: weather, terrain and vegetation.

Reads what the collectors already stored for that place rather than asking any
provider, so the assessment is repeatable and costs nothing."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from ecoguard.analyzers.fire.spread import live_moisture_from_ndvi, offset_point

logger = logging.getLogger(__name__)

# How much ground around the ignition point to characterise. Half a kilometre
# is the same default `surface_at` uses, and for the same reason: a fire is
# about to be on the ground around it, not only the ground under it. Wide
# enough to average out one odd raster cell, narrow enough that a valley floor
# and the ridge above it do not get blended into a slope neither of them has.
CONTEXT_RADIUS_M = 500.0

# When the tight radius finds no ground at all, widen once to half a grid cell
# before giving up. The surface grid is clipped to land the survey maps, so it
# has real holes — the Dead Sea shore is the obvious one, and a fire detected
# there sits 1.5 km from the nearest mapped cell. Reporting nothing for that
# fire is worse than characterising it from the nearest ground there is.
#
# The widening is recorded in `gaps` rather than hidden, because fuel sampled
# 2 km away is a weaker claim than fuel sampled under the fire, and a reader
# deciding how much to trust a spread forecast needs to know which they have.
WIDE_RADIUS_M = 2_500.0

# Vertices on the circle handed to PostGIS. Twenty-four is a third of a degree
# of error against a true circle at this radius — far finer than the ~270 m
# surface grid it is sampling, so more would cost a longer polygon for no
# change in the answer.
CIRCLE_VERTICES = 24

# How far out to look for settlements. The `possible` ring is the widest thing
# exposure is tested against, and at the rates this model produces it does not
# approach 25 km inside any plausible horizon — so this is a generous bound
# that keeps the query small rather than a limit anyone should reach.
LOCALITY_SEARCH_RADIUS_M = 25_000.0

# How far from the incident's own hour a weather reading may sit and still
# describe it. Matches the area-summary window, and for the same reason: the
# collector writes hourly, so six hours is five missed ticks of slack before a
# reading stops being about the same afternoon.
WEATHER_MAX_AGE_HOURS = 6

# Lag worth declaring. The collector writes hourly, so an hour of it is normal;
# past two the reading is describing a different part of the afternoon and the
# wind it carries may no longer be the wind the fire is running on.
STALE_WEATHER_HOURS = 2


def circle_around(latitude: float, longitude: float, radius_m: float) -> dict[str, Any]:
    """A GeoJSON polygon approximating a circle, for the area aggregates.

    Built with `spread.offset_point` rather than a second bearing/distance
    implementation, so this circle and the spread rings are round in exactly
    the same way.
    """
    ring = []
    for index in range(CIRCLE_VERTICES):
        bearing = index * 360.0 / CIRCLE_VERTICES
        point_lat, point_lon = offset_point(latitude, longitude, bearing, radius_m)
        ring.append([round(point_lon, 6), round(point_lat, 6)])
    ring.append(list(ring[0]))
    return {"type": "Polygon", "coordinates": [ring]}


def environment_for(
    incident: Mapping[str, Any], *, radius_m: float = CONTEXT_RADIUS_M
) -> dict[str, Any] | None:
    """The weather, terrain and fuel around an incident, keyed for `analyze()`.

    Args:
        incident: a coordinator incident. Only `latitude` and `longitude` are
            read.
        radius_m: how much ground around the point to characterise.

    Returns:
        dict in the shape `spread_analyzer.analyze` expects, with a `gaps` list
        naming anything that could not be read, or None when the incident has
        no position to read anything around.

    A missing reading is left absent and named in `gaps` rather than defaulted.
    `analyze()` falls back to its own documented defaults for temperature and
    humidity, but wind and cover have no sensible default — a fire modelled on
    a calm day it is not having is not a conservative estimate, it is a wrong
    one — so those stay missing and the caller can see why.
    """
    latitude, longitude = incident.get("latitude"), incident.get("longitude")
    if latitude is None or longitude is None:
        return None

    from ecoguard.database.repositories.area_summary import summarize_area

    def read(radius: float):
        """Read the environmental values within this radius of the fire."""
        try:
            return summarize_area(
                circle_around(float(latitude), float(longitude), radius)
            )
        except Exception:
            logger.exception("could not read the environment around the incident")
            return None

    summary = read(radius_m)
    if summary is None:
        return None

    gaps: list[str] = []
    sampled_radius_m = radius_m

    # The grid has holes where the survey maps no land. Widen once rather than
    # answer "no fuel here" for a fire that is plainly burning something.
    if not (summary.get("fuel") or {}).get("cell_count"):
        wider = read(WIDE_RADIUS_M)
        if wider is not None and (wider.get("fuel") or {}).get("cell_count"):
            summary = wider
            sampled_radius_m = WIDE_RADIUS_M
            gaps.append(
                f"ground_sampled_from_{int(WIDE_RADIUS_M)}m_away_no_data_at_the_point"
            )

    terrain = summary.get("terrain") or {}
    fuel = summary.get("fuel") or {}
    vegetation = summary.get("vegetation") or {}

    # Weather is read at the incident's own hour, not at the wall clock.
    #
    # `summarize_area` filters on now() - 6h, which is right for the operator
    # drawing a polygon on a live map and wrong for an incident. An incident
    # carries the time it was last seen, and for a replay, a drill or a backlog
    # processed after an outage that time is not now. Taking the area summary's
    # weather would have silently attached this afternoon's wind to a fire that
    # burned in August — no gap, no warning, a confident wrong answer. That is
    # the failure mode this whole module is written to avoid.
    weather = weather_at(incident, cells=summary.get("weather"))
    if not weather:
        gaps.append("no_weather_reading_for_the_incident_hour")
    elif (weather.get("age_hours") or 0) >= STALE_WEATHER_HOURS:
        # Only worth saying once it is more than one missed collector tick.
        # The reading is hourly, so an hour of lag is the normal case and
        # reporting it as a gap would train a reader to ignore the section.
        gaps.append(
            f"weather_is_{int(weather['age_hours'])}h_older_than_the_incident"
        )
    if not terrain.get("cell_count"):
        gaps.append("no_terrain_data_for_the_location")
    if not fuel.get("cell_count"):
        gaps.append("no_land_cover_for_the_location")
    if vegetation.get("ndvi") is None:
        # Not fatal: `analyze()` falls back to the calendar. Named anyway,
        # because a live moisture guessed from the month is a weaker claim than
        # one read off the ground, and the reader cannot tell them apart from
        # the number alone.
        gaps.append("no_ndvi_for_the_location_live_moisture_from_the_calendar")

    environment: dict[str, Any] = {
        "cover_fractions": dict(fuel.get("fractions") or {}),
        "observed_at": (weather or {}).get("observed_at"),
        "weather_cell_count": 1 if weather else 0,
        "sampled_radius_m": sampled_radius_m,
        "gaps": gaps,
        # Carried through unused by the spread model but wanted by the report:
        # the difference between a fire on a 4 degree mean slope and one with a
        # 30 degree face inside the same cell is the whole story.
        "slope_max_deg": terrain.get("slope_max_deg"),
        "elevation_m": terrain.get("elevation_m"),
        "built_up_fraction": fuel.get("built_up_fraction"),
        "burnable_fraction": fuel.get("burnable_fraction"),
        "dominant_fuel": fuel.get("dominant"),
        "fire_danger": summary.get("fire_danger"),
        # Carried for the report so the live moisture below can be read rather
        # than taken on trust.
        "ndvi": vegetation.get("ndvi"),
        "ndvi_observed_at": vegetation.get("observed_at"),
    }

    # The one place NDVI changes an answer: live fuel moisture off the ground
    # instead of off the calendar. Absent, `analyze()` uses the month, which is
    # why this is set rather than defaulted here.
    if vegetation.get("ndvi") is not None:
        environment["live_fuel_moisture"] = round(
            live_moisture_from_ndvi(vegetation["ndvi"]), 4
        )

    for key, value in (
        ("temperature_c", (weather or {}).get("temperature_c")),
        ("humidity_percent", (weather or {}).get("humidity_percent")),
        ("wind_speed_kmh", (weather or {}).get("wind_speed_kmh")),
        ("wind_direction_deg", (weather or {}).get("wind_direction_deg")),
        ("slope_deg", terrain.get("slope_deg")),
        ("aspect_deg", terrain.get("aspect_deg")),
    ):
        if value is not None:
            environment[key] = value

    return environment


def localities_for(
    incident: Mapping[str, Any], *, radius_m: float = LOCALITY_SEARCH_RADIUS_M
) -> tuple[dict[str, Any], ...]:
    """Settlements near the incident, in the record shape `exposure` reads.

    Reads the `towns` table rather than the committed GeoJSON. The file that
    `exposure.load_localities` defaults to holds six localities, which is a
    fixture; the table holds the national set with authoritative outlines, and
    carries the local authority's telephone number, the fire district and the
    responsible police station on the same rows — which is what turns "Yokneam
    is in the path" into something an operator can act on without a second
    lookup.

    Returns an empty tuple when the table is absent or unreachable. The caller
    must treat that as "not assessed", never as "nowhere is at risk".
    """
    latitude, longitude = incident.get("latitude"), incident.get("longitude")
    if latitude is None or longitude is None:
        return ()

    from ecoguard.database.repositories.towns import towns_with_outlines_near

    try:
        return towns_with_outlines_near(
            latitude=float(latitude), longitude=float(longitude), radius_m=radius_m
        )
    except Exception:
        logger.exception("could not read settlements near the incident")
        return ()


def population_within(ring: list[list[float]]) -> dict[str, Any] | None:
    """Residents inside one spread ring, area-weighted off the population grid.

    This is a different number from the locality populations `exposure` totals,
    and both are wanted. A whole-locality figure answers "which places are
    affected and how big are they"; this answers "how many people are inside
    the line on the map". Reporting either one alone invites it to be read as
    the other.

    Returns None when the ring is empty or the grid is not loaded — never a
    zero, which would read as an evacuated hillside rather than as an unasked
    question.
    """
    if not ring or len(ring) < 4:
        return None

    from ecoguard.database.repositories.area_summary import population_intersection

    try:
        result = population_intersection({"type": "Polygon", "coordinates": [ring]})
    except Exception:
        logger.exception("could not read the population inside the spread ring")
        return None

    if not result.get("grid_available"):
        return None
    return {
        "people": round(result["weighted_population"]),
        "grid_cells": result["intersected_cell_count"],
    }


def weather_at(
    incident: Mapping[str, Any], *, cells: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """The stored weather describing the hour this incident was last seen.

    Args:
        incident: a coordinator incident. `last_signal_at` decides the hour;
            `cells` or the coordinates decide the place.
        cells: ignored, accepted so a caller can pass the area summary's
            weather section without the signature changing later.

    Returns:
        The newest reading at or before the incident's hour and within
        `WEATHER_MAX_AGE_HOURS` of it, with `age_hours` saying how far back it
        had to reach. None when there is none — which the caller must report as
        a gap rather than fill with a default.
    """
    from sqlalchemy import text

    from ecoguard.database.engine import Session
    from ecoguard.shared.cells import cell_for

    cell_id = (incident.get("cells") or [None])[0]
    if not cell_id:
        latitude, longitude = incident.get("latitude"), incident.get("longitude")
        if latitude is None or longitude is None:
            return None
        cell_id = cell_for(float(latitude), float(longitude))
    if not cell_id:
        return None

    at = _incident_time(incident)
    try:
        with Session() as session:
            row = session.execute(
                text(
                    """
                    SELECT observed_at, payload FROM observations
                    WHERE source = 'weather' AND cell_id = :cell
                      AND observed_at <= :at
                      AND observed_at >= :at - make_interval(hours => :max_age)
                    ORDER BY observed_at DESC LIMIT 1
                    """
                ),
                {"cell": cell_id, "at": at, "max_age": WEATHER_MAX_AGE_HOURS},
            ).first()
    except Exception:
        logger.exception("could not read weather for the incident hour")
        return None

    if row is None:
        return None
    observed_at, payload = row
    payload = payload or {}

    def number(key: str) -> float | None:
        """One value from the reading as a number, or None when absent."""
        value = payload.get(key)
        return None if value is None else float(value)

    return {
        "observed_at": observed_at.isoformat(),
        "age_hours": round((at - observed_at).total_seconds() / 3600.0, 1),
        "temperature_c": number("temperature_2m"),
        "humidity_percent": number("relative_humidity_2m"),
        "wind_speed_kmh": number("wind_speed_10m"),
        "wind_direction_deg": number("wind_direction_10m"),
    }


def _incident_time(incident: Mapping[str, Any]) -> datetime:
    """When the incident is happening, for reading the weather of that hour."""
    for key in ("last_signal_at", "first_seen_at"):
        value = incident.get(key)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def history_for(incident: Mapping[str, Any]) -> dict[str, Any] | None:
    """What has burned here before, and whether this cell is a standing source.

    Two questions from one repository, both evaluated as of the incident's own
    time rather than now — so a replay sees only what was known then, and a
    fire is never judged against detections that had not happened yet.
    """
    latitude, longitude = incident.get("latitude"), incident.get("longitude")
    if latitude is None or longitude is None:
        return None

    from ecoguard.database.repositories.fire_history import fire_history, persistence

    at = _incident_time(incident)
    cell_id = (incident.get("cells") or [None])[0]
    try:
        record = dict(fire_history(float(latitude), float(longitude), at))
        if cell_id:
            record.update(persistence(cell_id, at))
        return record
    except Exception:
        logger.exception("could not read the fire history for this incident")
        return None
