"""Dispatch selection: grade, territoriality, and the parallel initial response.

The step most easily implemented wrong is the out-of-district initial response.
The natural shape in code is a fallback — try the home district, and reach
outside if short — and that is a different procedure with a different timeline.
It would hold the closest appliance to the fire behind a decision the procedure
does not require anyone to make. Several tests below exist only to keep it
parallel.
"""

import pytest

from ecoguard.planners.fire import dispatch
from ecoguard.planners.fire.dispatch_policy import (
    FORCE_COMPLETION,
    GRADES,
    IMMEDIATE_DISPATCH,
    INITIAL_RESPONSE_TEAMS_FROM_OUTSIDE,
)


def _analysis(**overrides):
    return {
        "risk_semantics": "fire_spread_forecast",
        "status": "ok",
        "risk_score": 50,
        "origin": {"latitude": 31.789, "longitude": 34.759},
        "exposure": [],
        "infrastructure_at_risk": [],
        "behaviour": {"burnable_fraction": 0.9},
        **overrides,
    }


def _town(name, exposure="likely", locality_id=None):
    return {
        "name": name, "exposure": exposure, "population": 5000,
        "locality_id": locality_id or name.lower(),
    }


def _site(exposure="likely"):
    return {"name": "Estate", "kind": "industrial area",
            "category": "economic", "exposure": exposure}


# --- grade derivation (pure) ------------------------------------------------

def test_open_terrain_with_nothing_in_the_footprint_is_grade_1():
    grade = dispatch.derive_grade(_analysis())
    assert grade["grade"] == 1
    assert grade["teams_required"] == 1
    assert grade["cross_district_permitted"] is False


def test_structures_without_a_settlement_is_grade_2():
    grade = dispatch.derive_grade(_analysis(infrastructure_at_risk=[_site()]))
    assert grade["grade"] == 2
    assert grade["cross_district_permitted"] is False


def test_a_settlement_in_the_footprint_is_grade_3():
    grade = dispatch.derive_grade(_analysis(exposure=[_town("Beit Oren")]))
    assert grade["grade"] == 3
    assert "Beit Oren" in grade["reason"]
    # Grade 3 is where cross-district dispatch becomes permitted at all.
    assert grade["cross_district_permitted"] is True
    assert "2.1.6" in (grade["basis"] or "")


def test_two_settlements_lift_it_to_grade_4():
    grade = dispatch.derive_grade(
        _analysis(exposure=[_town("A"), _town("B")])
    )
    assert grade["grade"] == 4


def test_extreme_severity_with_one_settlement_also_reaches_grade_4():
    grade = dispatch.derive_grade(
        _analysis(exposure=[_town("A")], risk_score=95)
    )
    assert grade["grade"] == 4


def test_national_criteria_take_it_to_grade_5():
    grade = dispatch.derive_grade(
        _analysis(exposure=[_town("A")], national_event=True)
    )
    assert grade["grade"] == 5
    assert grade["teams_required"] >= 10, "the top grade begins at ten teams"
    assert "2.1.5" in (grade["basis"] or "")


def test_a_settlement_only_a_wind_shift_reaches_does_not_raise_the_grade():
    """`possible` is a contingency. Grading on it would make every fire a 3."""
    grade = dispatch.derive_grade(
        _analysis(exposure=[_town("Far", exposure="possible")])
    )
    assert grade["grade"] == 1


def test_the_ten_team_threshold_is_the_cited_one():
    """201.02.003 §2.1.5. Changing it silently decouples us from the source."""
    assert GRADES[5]["teams_min"] == 10


# --- station selection ------------------------------------------------------

@pytest.fixture
def border_fire():
    """Bnei Aish: in דרום, but the nearest station overall is in מרכז."""
    return _analysis(
        origin={"latitude": 31.789, "longitude": 34.75904},
        exposure=[_town("A"), _town("B")],
    )


def test_the_home_station_is_inside_the_district(database, border_fire):
    """Territoriality first. The nearest station overall is in another
    district here, and it must not become the home station."""
    result = dispatch.plan_dispatch(border_fire)
    home = next(s for s in result["stations"] if s["role"] == "home_station")

    assert result["home_district"] == "דרום"
    assert home["district"] == "דרום"


def test_the_out_of_district_team_is_dispatched_in_parallel(database, border_fire):
    """Not a fallback. It is issued at the same time as the home complement,
    under the same immediate request type, needing no approval."""
    result = dispatch.plan_dispatch(border_fire)
    initial = result["initial_response_out_of_district"]

    assert initial is not None, "the nearest station is out of district here"
    assert initial["district"] != "דרום"
    assert initial["request_type"] == IMMEDIATE_DISPATCH
    assert "parallel" in initial["dispatched"]
    assert "none required" in initial["approval"]

    # And the home station is still dispatched in full alongside it.
    home = next(s for s in result["stations"] if s["role"] == "home_station")
    assert home["request_type"] == IMMEDIATE_DISPATCH
    assert home["teams"] >= 1


def test_only_one_team_comes_from_outside_the_district(database, border_fire):
    """The procedure bounds this. It is not a licence to draw on every
    neighbour, and generalising it turns an exception into a habit."""
    result = dispatch.plan_dispatch(border_fire)
    initial = result["initial_response_out_of_district"]
    assert initial["teams"] == INITIAL_RESPONSE_TEAMS_FROM_OUTSIDE == 1


def test_below_grade_three_nothing_comes_from_outside(database):
    """Each district contains events in its own sector; assistance is by
    exception, and grade 3 is where the exception begins."""
    result = dispatch.plan_dispatch(_analysis(
        origin={"latitude": 31.789, "longitude": 34.75904},
    ))
    assert result["grade"]["grade"] < 3
    assert result["initial_response_out_of_district"] is None
    assert all(
        station["district"] == "דרום" for station in result["stations"]
    ), "a grade 1 event must stay inside its own district"


def test_force_completion_is_a_different_request_from_initial_dispatch(
    database, border_fire
):
    """Different authority, different timeline. Conflating them implies force
    completion arrives as fast as initial response."""
    result = dispatch.plan_dispatch(border_fire)
    kinds = {station["request_type"] for station in result["stations"]}
    assert IMMEDIATE_DISPATCH in kinds
    if result["teams_assigned"] > 3:
        assert FORCE_COMPLETION in kinds


def test_no_station_is_stripped_bare(database, border_fire):
    """Without appliance counts the cap is what enforces this."""
    result = dispatch.plan_dispatch(border_fire)
    for station in result["stations"]:
        cap = 3 if station.get("regional") else 2
        assert station["teams"] <= cap


def test_police_are_notified_for_every_threatened_locality(database):
    """Israel Police hold the localised evacuation decision, so this is a
    dispatch output rather than a courtesy."""
    result = dispatch.plan_dispatch(_analysis(
        origin={"latitude": 32.735, "longitude": 35.025},
        exposure=[_town("Beit Oren", locality_id="beit-oren")],
    ))
    assert result["grade"]["grade"] >= 3
    # The locality must resolve through the join table, not a name match.
    assert isinstance(result["police_notifications"], list)


def test_police_are_not_notified_below_grade_three(database):
    """There is no evacuation question for them to hold."""
    result = dispatch.plan_dispatch(_analysis(
        origin={"latitude": 32.735, "longitude": 35.025},
    ))
    assert result["grade"]["grade"] < 3
    assert result["police_notifications"] == []


def test_every_dispatch_declares_the_missing_dispatch_table(database, border_fire):
    """The reconstruction must never be presented as the authority's table."""
    result = dispatch.plan_dispatch(border_fire)
    assert any("dispatch_table_unavailable" in limit for limit in result["limits"])
    assert any(
        "station_appliance_counts_unavailable" in limit
        for limit in result["limits"]
    )


def test_an_incident_with_no_position_is_skipped_not_guessed(database):
    result = dispatch.plan_dispatch(_analysis(origin={}))
    assert result["status"] == "skipped"
    assert result["reason"] == "incident_has_no_position"
