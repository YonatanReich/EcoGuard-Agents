"""The report an operator acts on: evacuation order, counts, honest absences.

Pure and offline. Every locality here is passed in explicitly, so none of this
touches the store — the same split `spread_analyzer` has always claimed.
"""

from datetime import datetime, timezone

import pytest

from ecoguard.analyzers.emergency.fire.spread_analyzer import (
    EVACUATE_NOW,
    PREPARE,
    STANDBY,
    analyze,
    build_report,
    evacuation_priorities,
)

WHEN = datetime(2026, 8, 15, 13, 0, tzinfo=timezone.utc)

# A hot, dry, windy afternoon — conditions that actually move a fire, so the
# rings reach the towns below rather than testing an empty path.
KHAMSIN = {
    "temperature_c": 42.0,
    "humidity_percent": 12.0,
    "wind_speed_kmh": 55.0,
    "wind_direction_deg": 90.0,
    "slope_deg": 10.0,
    "slope_max_deg": 26.0,
    "aspect_deg": 270.0,
    "cover_fractions": {
        "tree_cover": 0.5, "shrubland": 0.3, "grassland": 0.15, "built_up": 0.05
    },
    "gaps": [],
}

INCIDENT = {
    "id": "test-incident",
    "primary_hazard": "fire",
    "latitude": 32.73,
    "longitude": 35.03,
    "last_signal_at": WHEN,
}


def _square(centre_lat, centre_lon, half_deg):
    """One square outline around a point, in the ring shape exposure reads."""
    return (
        tuple([
            (centre_lon - half_deg, centre_lat - half_deg),
            (centre_lon + half_deg, centre_lat - half_deg),
            (centre_lon + half_deg, centre_lat + half_deg),
            (centre_lon - half_deg, centre_lat + half_deg),
            (centre_lon - half_deg, centre_lat - half_deg),
        ]),
    )


def _town(name, lat, lon, population, **extra):
    return {
        "locality_id": name.lower(),
        "name": name,
        "name_he": name,
        "population": population,
        "rings": _square(lat, lon, 0.004),
        **extra,
    }


# --- evacuation ordering ---------------------------------------------------

def test_a_burning_settlement_is_immediate_and_carries_no_countdown():
    priorities = evacuation_priorities([
        {"name": "Inside", "exposure": "burning", "arrival_minutes": None,
         "population": 900, "distance_m": 0.0},
    ])
    assert priorities[0]["priority"] == EVACUATE_NOW
    assert priorities[0]["arrival_minutes"] is None


@pytest.mark.parametrize("minutes,expected", [
    (15.0, EVACUATE_NOW),
    (60.0, EVACUATE_NOW),   # the boundary is inclusive
    (61.0, PREPARE),
    (170.0, PREPARE),
])
def test_arrival_time_decides_between_immediate_and_prepare(minutes, expected):
    priorities = evacuation_priorities([
        {"name": "Town", "exposure": "likely", "arrival_minutes": minutes,
         "population": 500, "distance_m": 1000.0},
    ])
    assert priorities[0]["priority"] == expected


def test_a_wind_shift_town_is_standby_not_prepare():
    priorities = evacuation_priorities([
        {"name": "Sideways", "exposure": "possible", "arrival_minutes": None,
         "population": 500, "distance_m": 4000.0},
    ])
    assert priorities[0]["priority"] == STANDBY


def test_the_order_is_worst_first_then_soonest():
    priorities = evacuation_priorities([
        {"name": "Far", "exposure": "possible", "arrival_minutes": None,
         "population": 100, "distance_m": 9000.0},
        {"name": "Later", "exposure": "likely", "arrival_minutes": 150.0,
         "population": 100, "distance_m": 5000.0},
        {"name": "Burning", "exposure": "burning", "arrival_minutes": None,
         "population": 100, "distance_m": 0.0},
        {"name": "Soon", "exposure": "likely", "arrival_minutes": 30.0,
         "population": 100, "distance_m": 900.0},
    ])
    assert [item["name"] for item in priorities] == ["Burning", "Soon", "Later", "Far"]


def test_contact_details_travel_when_present_and_are_absent_when_not():
    priorities = evacuation_priorities([
        {"name": "Known", "exposure": "likely", "arrival_minutes": 40.0,
         "population": 500, "distance_m": 900.0,
         "authority_phone": "04-8356356", "fire_district": "Coast"},
        {"name": "Unknown", "exposure": "likely", "arrival_minutes": 45.0,
         "population": 500, "distance_m": 950.0},
    ])
    assert priorities[0]["authority_phone"] == "04-8356356"
    # Absent, not blank: a caller must be able to tell "we do not have it"
    # from "there isn't one".
    assert priorities[1]["authority_phone"] is None


# --- the report ------------------------------------------------------------

def _report_for(towns, **kwargs):
    result = analyze(INCIDENT, KHAMSIN, horizon_minutes=240, localities=towns, **kwargs)
    assert result["status"] == "ok", result["reason"]
    return result


def test_the_report_names_the_town_in_the_path_with_its_arrival():
    # Due west of the ignition point, which is where an east wind sends it.
    downwind = _town("Downwind", 32.73, 34.98, 4200, authority_phone="04-1234567")
    result = _report_for([downwind])

    assert result["exposure"], "an east wind should carry the fire onto a town due west"
    report = result["report"]
    assert "Downwind" in report
    assert "4,200" in report
    assert "EVACUATION PRIORITY" in report
    assert "04-1234567" in report


def test_every_section_is_present_even_when_nothing_is_at_risk():
    result = _report_for([])
    report = result["report"]
    for heading in ("SITUATION", "FORECAST SPREAD", "PEOPLE AT RISK",
                    "SETTLEMENTS IN THE PATH", "EVACUATION PRIORITY",
                    "SEVERITY", "LIMITS"):
        assert heading in report, heading
    # An empty section says so rather than being dropped — a missing section is
    # indistinguishable from a bug.
    assert "No populated locality lies in the forecast path." in report


def test_an_uncounted_population_is_never_reported_as_zero():
    result = _report_for([], ring_population=None)
    assert result["population_in_spread"] is None
    assert "This is not a count of zero." in result["report"]


def test_a_counted_population_is_stated_with_its_provenance():
    result = _report_for([], ring_population={"people": 738, "grid_cells": 41})
    assert "738 people" in result["report"]
    assert result["population_in_spread"] == {"people": 738, "grid_cells": 41}


def test_a_stalled_fire_reports_no_spread_without_implying_safety():
    wet = {**KHAMSIN, "humidity_percent": 100.0, "dead_fuel_moisture": 0.9}
    result = analyze(INCIDENT, wet, horizon_minutes=240, localities=[])

    assert result["status"] == "stalled"
    assert result["risk_score"] is None, "a stalled fire is unscored, not zero"
    assert result["evacuation"] == []
    # It must say what it is *not* claiming.
    assert "not the fire" in result["report"]
    assert "LIMITS" in result["report"]


def test_the_report_distinguishes_people_in_the_ring_from_whole_settlements():
    """Two different counts that must never be read as each other."""
    downwind = _town("Downwind", 32.73, 34.98, 289507)
    result = _report_for([downwind], ring_population={"people": 738, "grid_cells": 41})
    report = result["report"]

    assert "738 people" in report
    assert "289,507" in report
    assert "Whole-settlement totals" in report


def test_severity_names_what_drove_it():
    downwind = _town("Downwind", 32.73, 34.98, 4200)
    result = _report_for([downwind])
    assert "Driven by:" in result["report"]
    assert str(result["risk_score"]) in result["report"]


def test_evidence_gaps_reach_the_report():
    environment = {**KHAMSIN, "gaps": ["no_weather_reading_near_the_incident"]}
    result = analyze(INCIDENT, environment, horizon_minutes=240, localities=[])
    assert "EVIDENCE GAPS" in result["report"]
    assert "no weather reading near the incident" in result["report"]


def test_build_report_is_callable_without_a_score():
    """An unscored forecast still produces a report, and says it is unscored."""
    result = analyze(INCIDENT, KHAMSIN, horizon_minutes=240, localities=[])
    report = build_report(
        result["origin"], result["behaviour"], result["spread"],
        result["exposure"], result["evacuation"], KHAMSIN, None, None, 240.0,
    )
    assert "Not scored" in report
    assert "not a low score" in report
