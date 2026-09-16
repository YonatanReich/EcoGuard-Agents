"""The fire spread analyser, against artificial incidents with a known answer.

Two layers of check, and they fail for different reasons.

`test_published_rate_of_spread_is_reproduced` is the physics. Rothermel is not
ours and its published outputs are not negotiable, so the Anderson 1982 table
is the ground truth and any drift away from it is a bug in this repository. It
runs first because every other number here is downstream of it: if the rate of
spread is wrong, the polygon, the arrival times and the named towns are all
confidently wrong together.

The case suite in data/evaluation/fire_spread_cases.json is the product
behaviour. Each case is an artificial coordinator incident whose right answer
was worked out from the map and the physics *before* the analyser was run, and
is recorded in that file next to the case. The expectations are deliberately
not tight recordings of current output — a distance is checked to 250 m because
the locality outlines are only good to about 200 m, and asserting tighter than
the input data supports produces a test that fails on rounding and teaches
nobody anything.

The pair that carries the most weight is cases 01 and 02. They differ in one
number, the wind bearing, and they must name different towns. A system that
passes 01 alone may only be listing whatever is nearby.
"""

from __future__ import annotations

import json

import pytest

from ecoguard.analyzers.emergency.fire.spread import (
    FT_MIN_TO_M_MIN,
    rate_of_spread,
    spread_rings,
    wind_adjustment_factor,
)
from ecoguard.analyzers.emergency.fire.spread_analyzer import analyze, compass_point
from ecoguard.paths import EVALUATION

CASES_PATH = EVALUATION / "fire_spread_cases.json"
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
BY_ID = {case["case_id"]: case for case in CASES}

# One chain per hour in m/min. Anderson publishes in chains per hour and
# converting his table into our units once, here, is safer than converting
# every expectation by hand.
CHAIN_PER_HOUR = 66.0 / 60.0 * FT_MIN_TO_M_MIN

# Anderson 1982, INT-122: head rate of spread in chains/hour at 8% dead fuel
# moisture, 100% live fuel moisture, 5 mi/h midflame wind and no slope.
#
# The tolerance is per model and each value is a statement about a known
# approximation, not a slack budget. FM5 is the loose one: the implementation
# weights fuel classes by surface area alone, where BEHAVE additionally applies
# Rothermel's size-class grouping, and brush - with the widest spread of class
# sizes in the set - is where that simplification costs the most. Under-reading
# brush by a fifth is a real limitation of this analyser and is written down
# rather than absorbed by a wide global tolerance.
PUBLISHED_SPREAD = {
    "FM1": ({"grassland": 1.0}, 78.0, 0.10),
    "FM3": ({"cropland": 1.0}, 104.0, 0.10),
    "FM5": ({"shrubland": 1.0}, 18.0, 0.25),
    "FM9": ({"tree_cover": 1.0}, 7.5, 0.10),
}


@pytest.mark.parametrize("code", sorted(PUBLISHED_SPREAD))
def test_published_rate_of_spread_is_reproduced(code):
    """The model reproduces Anderson's table for the fuels Israel actually has.

    The midflame wind is what the table quotes, so the canopy reduction the
    model applies internally has to be undone to hand it the right wind — using
    the model's own factor, never a second copy of that rule, because a copy
    that drifts would make this test confirm a number the analyser cannot
    produce. The crown-fire adjustment is divided out for the same reason: it
    is our claim about pine, not Anderson's about litter.
    """
    cover, published_chains, tolerance = PUBLISHED_SPREAD[code]
    midflame_kmh = 5.0 * 1.609344
    behaviour = rate_of_spread(
        cover,
        dead_fuel_moisture=0.08,
        wind_speed_kmh=midflame_kmh / wind_adjustment_factor(cover),
        slope_deg=0.0,
        live_fuel_moisture=1.00,
    )
    assert behaviour["fuel"]["fuel_model_code"] == code
    surface = behaviour["head_ros_m_per_min"] / behaviour["fuel"]["spread_adjustment"]
    modelled_chains = surface / CHAIN_PER_HOUR
    error = abs(modelled_chains - published_chains) / published_chains
    assert error <= tolerance, (
        f"{code}: modelled {modelled_chains:.1f} ch/h against published "
        f"{published_chains} ch/h, {error:.1%} off (tolerance {tolerance:.0%})"
    )


def test_wet_fuel_stops_the_fire_whatever_the_wind_does():
    """Above the extinction moisture the rate is exactly zero, not merely small.

    Worth its own test because it is the one place in the model where a large
    input produces no output at all, and an implementation that let a strong
    wind leak past the damping term would be wrong in the most dangerous
    direction available: reporting spread on a morning there is none, and
    being believed the next time.
    """
    for wind in (0.0, 30.0, 90.0):
        behaviour = rate_of_spread(
            {"grassland": 1.0},
            dead_fuel_moisture=0.20,  # FM1 extinguishes at 0.12
            wind_speed_kmh=wind,
            slope_deg=25.0,
        )
        assert behaviour["head_ros_m_per_min"] == 0.0
        assert behaviour["reason"] == "fuel_above_moisture_of_extinction"


def test_fire_runs_upslope_when_the_air_is_still():
    """With no wind the slope decides the heading, and fire runs uphill.

    `aspect_deg` is the direction the ground *faces*, which is downhill. This
    pins the sign: a slope facing north must send the fire south.
    """
    behaviour = rate_of_spread(
        {"shrubland": 1.0}, dead_fuel_moisture=0.06, wind_speed_kmh=0.0, slope_deg=25.0
    )
    rings = spread_rings(
        32.75, 35.03, behaviour,
        wind_direction_deg=0.0, aspect_deg=0.0, horizon_minutes=60.0,
    )
    assert rings["status"] == "ok"
    assert compass_point(rings["heading_deg"]) == "south"


def test_possible_ring_always_contains_the_likely_one():
    """The wind-error union can only ever add reach, never remove it.

    If it could shrink, a locality could appear in the likely path and be
    absent from the possible one, which is incoherent and would let the report
    contradict itself in the same paragraph.
    """
    case = BY_ID["spread-01-petah-tikva-runs-west"]
    result = analyze(case["incident"], case["environment"], horizon_minutes=180.0)
    radii = result["spread"]["radii_m"]
    for bearing, likely in radii["likely"].items():
        assert radii["possible"][bearing] >= likely - 1e-6


@pytest.mark.parametrize("case", CASES, ids=[case["case_id"] for case in CASES])
def test_artificial_incident_produces_the_known_answer(case):
    """One artificial coordinator incident against its independently known truth."""
    expected = case["expected"]
    result = analyze(
        case["incident"],
        case["environment"],
        horizon_minutes=case.get("horizon_minutes", 180.0),
    )
    why = f"\ncase: {case['case_id']}\nground truth: {case['ground_truth']}\ngot: {result}"

    assert result["status"] == expected["status"], why
    assert result["risk_semantics"] == "fire_spread_forecast", why
    if "reason" in expected:
        assert result["reason"] == expected["reason"], why

    # A skip or a stall must never look like an assessment that found nothing
    # wrong. None, not zero, all the way out.
    if expected["status"] != "ok":
        assert result["risk_score"] is None, why
        assert result["risk_level"] is None, why

    if "origin_locality" in expected:
        assert result["origin"]["locality"] == expected["origin_locality"], why
    if "risk_level" in expected:
        assert result["risk_level"] == expected["risk_level"], why

    if "heading_compass" in expected:
        assert result["behaviour"]["heading_compass"] == expected["heading_compass"], why
    if "heading_deg" in expected:
        target, tolerance = expected["heading_deg"]["value"], expected["heading_deg"]["tolerance"]
        gap = abs((result["behaviour"]["heading_deg"] - target + 180.0) % 360.0 - 180.0)
        assert gap <= tolerance, why
    if "head_ros_m_per_min" in expected:
        band = expected["head_ros_m_per_min"]
        assert band["min"] <= result["behaviour"]["head_ros_m_per_min"] <= band["max"], why

    exposure = {item["locality_id"]: item for item in result["exposure"]}
    for locality_id, level in expected.get("exposure", {}).items():
        assert locality_id in exposure, f"{locality_id} was not named at all{why}"
        assert exposure[locality_id]["exposure"] == level, why
    for locality_id in expected.get("not_exposed", ()):
        assert locality_id not in exposure, f"{locality_id} named but is not at risk{why}"

    for locality_id, band in expected.get("distance_m", {}).items():
        assert abs(exposure[locality_id]["distance_m"] - band["value"]) <= band["tolerance"], why
    for locality_id, band in expected.get("arrival_minutes", {}).items():
        arrival = exposure[locality_id]["arrival_minutes"]
        assert arrival is not None, f"{locality_id} has no arrival time{why}"
        assert band["min"] <= arrival <= band["max"], why

    headline = result["headline"] or ""
    for fragment in expected.get("headline_contains", ()):
        assert fragment in headline, f"headline missing {fragment!r}{why}"
    for fragment in expected.get("headline_excludes", ()):
        assert fragment not in headline, f"headline wrongly contains {fragment!r}{why}"


def test_reversing_the_wind_changes_which_towns_are_named():
    """The pair that proves the forecast is a forecast.

    Cases 01 and 02 are the same fire in the same hour with the wind bearing
    reversed and nothing else touched. If both name Givat Shmuel then the
    analyser is reporting neighbours rather than predicting anything, and every
    other assertion in this file would still pass while it did so.
    """
    west = analyze(
        BY_ID["spread-01-petah-tikva-runs-west"]["incident"],
        BY_ID["spread-01-petah-tikva-runs-west"]["environment"],
        horizon_minutes=180.0,
    )
    east = analyze(
        BY_ID["spread-02-petah-tikva-runs-east"]["incident"],
        BY_ID["spread-02-petah-tikva-runs-east"]["environment"],
        horizon_minutes=180.0,
    )

    named = lambda result, level: {
        item["locality_id"] for item in result["exposure"] if item["exposure"] == level
    }
    assert "givat-shmuel" in named(west, "likely")
    assert "givat-shmuel" not in named(east, "likely")
    assert "givat-shmuel" not in named(east, "possible")

    # The one input that differs, and the one output that must follow it.
    assert west["behaviour"]["heading_compass"] == "west"
    assert east["behaviour"]["heading_compass"] == "east"
    assert west["behaviour"]["head_ros_m_per_min"] == east["behaviour"]["head_ros_m_per_min"]


def test_every_case_declares_its_limits():
    """The caveats travel with the forecast, including when there is no forecast.

    The result is what gets forwarded; the module docstring stays behind. An
    unsuppressed-spread polygon read as a prediction of what will actually
    happen is the specific misreading this analyser most invites.
    """
    for case in CASES:
        result = analyze(case["incident"], case["environment"])
        assert result["limits"], case["case_id"]
        assert any("no crew" in limit for limit in result["limits"]), case["case_id"]
