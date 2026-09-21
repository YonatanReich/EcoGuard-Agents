"""The incident's weather must be the incident's, not the wall clock's.

`environment_for` used to read weather through `summarize_area`, which filters
on `now() - 6 hours`. That is correct for the operator drawing a polygon on a
live map and wrong for an incident, which carries the time it was last seen. A
replay, a drill, or a backlog processed after an outage would have been handed
this afternoon's wind for a fire that burned in August — with no gap recorded,
because from the query's point of view nothing was missing.

That is the worst shape a bug can take here: a confident wrong answer in a
module whose entire design is about not producing one. These are the checks
that would have caught it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.analyzers.emergency.fire.environment import (
    WEATHER_MAX_AGE_HOURS,
    _incident_time,
    environment_for,
    weather_at,
)
from ecoguard.shared.cells import cell_for

CARMEL = (32.7350, 35.0250)

# Comfortably outside any retention window, so this stays true as the store
# rolls forward. The point is not that 2019 is special; it is that an incident
# far enough in the past has no stored weather and must say so.
LONG_AGO = datetime(2019, 8, 14, 13, 40, tzinfo=timezone.utc)


def _incident(when: datetime) -> dict:
    latitude, longitude = CARMEL
    return {
        "id": "TEST-weather-time",
        "primary_hazard": "fire",
        "latitude": latitude,
        "longitude": longitude,
        "cells": [cell_for(latitude, longitude)],
        "last_signal_at": when,
    }


# --- the pure half: which hour is asked about -----------------------------

def test_the_hour_asked_about_is_the_incidents_last_signal():
    when = datetime(2026, 8, 14, 13, 40, tzinfo=timezone.utc)
    assert _incident_time(_incident(when)) == when


def test_first_seen_is_used_when_there_is_no_last_signal():
    when = datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc)
    assert _incident_time({"first_seen_at": when}) == when


def test_an_iso_string_is_accepted_as_well_as_a_datetime():
    """Incidents arrive as rows from the driver and as JSON from a replay."""
    assert _incident_time(
        {"last_signal_at": "2026-08-14T13:40:00Z"}
    ) == datetime(2026, 8, 14, 13, 40, tzinfo=timezone.utc)


def test_an_incident_with_no_time_falls_back_to_now_rather_than_raising():
    before = datetime.now(timezone.utc)
    resolved = _incident_time({})
    assert before <= resolved <= datetime.now(timezone.utc) + timedelta(seconds=5)


# --- the half that needs the store ----------------------------------------

def test_a_long_past_incident_gets_no_weather_rather_than_todays(database):
    """The bug, stated as a test.

    Before the fix this returned the current hour's wind and temperature with
    an empty gap list, which is indistinguishable from a correct reading.
    """
    environment = environment_for(_incident(LONG_AGO))

    assert environment is not None, "terrain and fuel are still readable"
    assert environment.get("wind_speed_kmh") is None
    assert environment.get("temperature_c") is None
    assert environment.get("humidity_percent") is None
    assert "no_weather_reading_for_the_incident_hour" in environment["gaps"]


def test_weather_at_refuses_an_hour_it_has_no_reading_for(database):
    assert weather_at(_incident(LONG_AGO)) is None


def test_a_reading_is_never_taken_from_after_the_incident(database):
    """Hindsight is the other direction of the same mistake.

    A reading stamped later than the incident describes weather the fire had
    not met yet. Whatever the store holds, what comes back must be at or
    before the hour asked about.
    """
    reading = weather_at(_incident(datetime.now(timezone.utc)))
    if reading is None:
        pytest.skip("no recent weather stored to check against")

    observed_at = datetime.fromisoformat(reading["observed_at"])
    assert observed_at <= datetime.now(timezone.utc)
    assert 0 <= reading["age_hours"] <= WEATHER_MAX_AGE_HOURS
