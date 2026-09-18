"""The four things the coordinator exists to do, and the ways each fails quietly.

Deduplication is the one worth the most care, because both failure directions
are invisible in different ways. Over-splitting shows up as duplicate incidents
that somebody notices and complains about. Over-merging hides a real second
event inside the first, and nobody ever finds out — so the tests here pin the
boundary from both sides: a three-day fire stays one incident, and the same
cell a week later becomes a second one.

Causal packaging is tested against wind, not proximity, because that is the
whole reason it is not a radius check. The same pollution reading at the same
distance must merge when it is downwind of the fire and must not when it is
upwind, and nothing else about the two cases differs.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from ecoguard.coordinator import incidents as store
from ecoguard.coordinator.agent import coordinate
from ecoguard.coordinator.matching import (
    best_match,
    has_gone_quiet,
    matches,
    quiet_period_for,
)
from ecoguard.coordinator.packaging import (
    angular_gap,
    bearing_between,
    travel_bearing,
)
from ecoguard.coordinator.queues import (
    EMERGENCY,
    NON_EMERGENCY,
    UnroutableHazard,
    is_hybrid,
    queue_for,
    queues_for,
)
from ecoguard.shared.cells import service_area_cells
from ecoguard.shared.signals import (
    AIR_POLLUTION,
    FIRE,
    FLOOD,
    HIGH,
    VIIRS_PIXEL_M,
    CellLocation,
    CellSignal,
)


def test_flood_quiet_period_is_three_hours():
    assert quiet_period_for(FLOOD) == timedelta(hours=3)

WHEN = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _signal(cell_id, *, at=WHEN, hazard=FIRE, variable="frp", value=9.11,
            rarity=0.99, location=None):
    cell = store.incident_by_id  # noqa: F841 - keep import honest
    return CellSignal(
        cell_id=cell_id, observed_at=at, hazard=hazard, variable=variable,
        value=value, unit="MW", source="firms", rarity=rarity, direction=HIGH,
        location=location,
    )


@pytest.fixture
def clean(database):
    """A table with nothing in it, before and after."""
    with database.connect() as connection:
        connection.execute(text("DELETE FROM incidents"))
        connection.commit()
    yield
    with database.connect() as connection:
        connection.execute(text("DELETE FROM incidents"))
        connection.commit()


@pytest.fixture
def cells():
    """Three real cells: one, its neighbour, and one far away."""
    grid = {c.cell_id: c for c in service_area_cells()}
    home = next(
        c for c in service_area_cells()
        if f"risk-05000m-r{c.grid_row:04d}-c{c.grid_col + 1:04d}" in grid
    )
    neighbour = grid[f"risk-05000m-r{home.grid_row:04d}-c{home.grid_col + 1:04d}"]
    far = max(service_area_cells(), key=lambda c: abs(c.grid_row - home.grid_row))
    return home, neighbour, far


# --- requirement 1: event agnostic -----------------------------------------

def test_the_queues_route_by_response_not_severity():
    assert queue_for(FIRE) == EMERGENCY
    assert queue_for(AIR_POLLUTION) == NON_EMERGENCY


def test_an_unrouted_hazard_raises_rather_than_defaulting():
    # Defaulting would drop a new hazard into a queue nobody is watching, and
    # the failure is invisible: the queue is simply shorter than it should be.
    with pytest.raises(UnroutableHazard):
        queue_for("volcano")


def test_a_hybrid_belongs_to_both_queues():
    assert queues_for([FIRE, AIR_POLLUTION]) == (EMERGENCY, NON_EMERGENCY)
    assert is_hybrid([FIRE, AIR_POLLUTION]) is True
    assert is_hybrid([FIRE]) is False


# --- requirement 2: deduplication ------------------------------------------

def test_a_raging_fire_is_one_incident_not_forty(clean, cells):
    home, _, _ = cells
    # Three days of FIRMS ticks on the same cell, two hours apart.
    burst = [_signal(home.cell_id, at=WHEN + timedelta(hours=2 * n)) for n in range(36)]

    result = coordinate(burst, at=WHEN + timedelta(days=3))

    assert len(result.created) == 1
    assert len(result.updated) == 35
    incident = store.incident_by_id(result.created[0])
    assert incident["signal_count"] == 36


def test_a_fire_a_week_later_is_a_new_incident(clean, cells):
    home, _, _ = cells
    coordinate([_signal(home.cell_id, at=WHEN)], at=WHEN)

    later = WHEN + timedelta(days=7)
    result = coordinate([_signal(home.cell_id, at=later)], at=later)

    # The first went quiet and closed, so this is genuinely new rather than a
    # continuation of something a week old.
    assert len(result.created) == 1
    assert len(result.closed) == 1


def test_a_signal_one_cell_over_joins_rather_than_forking(clean, cells):
    home, neighbour, _ = cells

    result = coordinate(
        [_signal(home.cell_id, at=WHEN),
         _signal(neighbour.cell_id, at=WHEN + timedelta(minutes=30))],
        at=WHEN + timedelta(hours=1),
    )

    # A fire on a boundary lights pixels either side. Demanding an exact cell
    # match is the classic way one event becomes two.
    assert len(result.created) == 1
    assert len(result.updated) == 1
    assert set(store.incident_by_id(result.created[0])["cells"]) == {
        home.cell_id, neighbour.cell_id
    }


def test_a_distant_signal_starts_its_own_incident(clean, cells):
    home, _, far = cells

    result = coordinate(
        [_signal(home.cell_id, at=WHEN), _signal(far.cell_id, at=WHEN)], at=WHEN
    )

    assert len(result.created) == 2


def test_a_closed_incident_is_never_reopened(clean, cells):
    home, _, _ = cells
    incident = store.create_incident(
        store.next_incident_id(WHEN), _signal(home.cell_id), [EMERGENCY]
    )
    store.close_incident(incident["id"], WHEN)

    closed = store.incident_by_id(incident["id"])

    # Closing is a decision that the thing is over. Silently resurrecting it
    # would undo that decision without recording why.
    assert matches(_signal(home.cell_id), closed) is False


def test_matching_needs_the_same_hazard(clean, cells):
    home, _, _ = cells
    incident = store.create_incident(
        store.next_incident_id(WHEN), _signal(home.cell_id), [EMERGENCY]
    )

    pollution = _signal(home.cell_id, hazard=AIR_POLLUTION, variable="pm25")

    # Cross-hazard joining is causation, not identity, and lives in packaging.
    assert matches(pollution, store.incident_by_id(incident["id"])) is False


def test_the_closest_in_time_wins_when_several_match(clean, cells):
    home, _, _ = cells
    near = {"id": "A", "status": "open", "hazards": [FIRE], "cells": [home.cell_id],
            "last_signal_at": WHEN - timedelta(minutes=10)}
    far = {"id": "B", "status": "open", "hazards": [FIRE], "cells": [home.cell_id],
           "last_signal_at": WHEN - timedelta(hours=2)}

    assert best_match(_signal(home.cell_id), [far, near])["id"] == "A"


def test_quiet_is_judged_per_hazard():
    fire = {"primary_hazard": FIRE, "last_signal_at": WHEN}
    smog = {"primary_hazard": AIR_POLLUTION, "last_signal_at": WHEN}
    twelve_hours_later = WHEN + timedelta(hours=12)

    # A fire nothing has seen for twelve hours is out. An air quality episode
    # routinely goes quiet overnight and resumes; calling that two episodes
    # would double-count it.
    assert has_gone_quiet(fire, twelve_hours_later) is True
    assert has_gone_quiet(smog, twelve_hours_later) is False


def test_a_better_fix_replaces_a_worse_one_rather_than_averaging(clean, cells):
    home, _, _ = cells
    vague = CellLocation(home.latitude, home.longitude, 2000.0, "locality_geocode")
    precise = CellLocation(home.latitude + 0.01, home.longitude, VIIRS_PIXEL_M, "viirs_pixel")

    result = coordinate([
        _signal(home.cell_id, at=WHEN, location=vague),
        _signal(home.cell_id, at=WHEN + timedelta(minutes=20), location=precise),
    ], at=WHEN + timedelta(hours=1))

    incident = store.incident_by_id(result.created[0])
    # Averaging a 375 m fix with a 2 km one produces a place neither source
    # suggested and throws the good fix away.
    assert incident["precision_m"] == pytest.approx(VIIRS_PIXEL_M)
    assert incident["latitude"] == pytest.approx(precise.latitude)


def test_a_late_arriving_old_reading_cannot_drag_an_incident_backwards(clean, cells):
    home, _, _ = cells
    result = coordinate([
        _signal(home.cell_id, at=WHEN),
        _signal(home.cell_id, at=WHEN - timedelta(hours=2)),   # FIRMS runs late
    ], at=WHEN)

    incident = store.incident_by_id(result.created[0])
    assert incident["last_signal_at"] == WHEN


# --- requirement 3: causal packaging ---------------------------------------

def test_wind_direction_is_converted_to_a_travel_bearing():
    # wind_direction_10m is meteorological: the bearing it blows FROM. Getting
    # this backwards searches the exact half of the map the plume is not in.
    assert travel_bearing(19.0) == pytest.approx(199.0)
    assert travel_bearing(199.0) == pytest.approx(19.0)
    assert travel_bearing(0.0) == pytest.approx(180.0)


def test_bearings_wrap_when_compared():
    # 350 and 10 are twenty degrees apart; plain subtraction calls it 340.
    assert angular_gap(350.0, 10.0) == pytest.approx(20.0)
    assert angular_gap(10.0, 350.0) == pytest.approx(20.0)
    assert angular_gap(0.0, 180.0) == pytest.approx(180.0)


def test_bearing_between_points_north_and_east():
    assert bearing_between(32.0, 35.0, 33.0, 35.0) == pytest.approx(0.0, abs=1.0)
    assert bearing_between(32.0, 35.0, 32.0, 36.0) == pytest.approx(90.0, abs=1.0)


# --- requirement 4: the two queues -----------------------------------------

def test_a_fire_lands_in_the_emergency_queue_only(clean, cells):
    home, _, _ = cells

    result = coordinate([_signal(home.cell_id)], at=WHEN)

    assert len(result.emergency) == 1
    assert result.non_emergency == []


def test_pollution_lands_in_the_advisory_queue_only(clean, cells):
    home, _, _ = cells

    result = coordinate(
        [_signal(home.cell_id, hazard=AIR_POLLUTION, variable="pm25")], at=WHEN
    )

    assert result.emergency == []
    assert len(result.non_emergency) == 1


def test_an_unroutable_hazard_is_skipped_without_stopping_the_run(clean, cells):
    home, _, far = cells

    result = coordinate(
        [_signal(home.cell_id, hazard="volcano"), _signal(far.cell_id, hazard=FIRE)],
        at=WHEN,
    )

    # One detector nobody has routed must not prevent the others coordinating.
    assert len(result.skipped) == 1
    assert len(result.emergency) == 1


def test_the_queues_hold_incidents_not_signals(clean, cells):
    home, _, _ = cells

    result = coordinate(
        [_signal(home.cell_id, at=WHEN + timedelta(minutes=n * 10)) for n in range(5)],
        at=WHEN + timedelta(hours=1),
    )

    # Five sightings of one fire is one thing to analyse, which is the whole
    # point of this stage.
    assert len(result.emergency) == 1
    assert result.emergency[0]["signal_count"] == 5


# --- requirement 3, end to end: the hybrid ---------------------------------

def _weather_hour(database):
    """The newest stored weather hour, which is the 'now' these tests need.

    Anchored to the data rather than to the wall clock. `wind_direction_at`
    looks back six hours, so a test that asked about the real present passed
    only while the collector was up to date and began failing a few hours
    after it fell behind - a red suite caused by collection lag, in tests that
    are about causal linking and have nothing to say about freshness.
    """
    with database.connect() as connection:
        newest = connection.execute(
            text("SELECT max(observed_at) FROM observations "
                 "WHERE source = 'weather' AND issued_at IS NULL")
        ).scalar()
    if newest is None:
        pytest.skip("no stored weather to take a wind direction from")
    return newest.replace(minute=0, second=0, microsecond=0)


def _windy_cell(at):
    """A cell with stored wind AND room on both sides, so the causal tests run.

    Searched rather than hardcoded, and searched for the whole property rather
    than just for wind: an edge cell can have a perfectly good wind reading and
    still have no land upwind of it, and a test that skipped for that reason
    would prove nothing about the thing it was written to prove.
    """
    for cell in service_area_cells()[::17]:
        if _wind_split(cell.cell_id, at) is not None:
            return cell.cell_id
    return None


def _wind_split(cell_id, at):
    """A downwind and an upwind cell for a real cell, or None if no wind.

    Chosen at runtime from the stored wind rather than hardcoded, because the
    whole claim under test is that the link follows the weather.
    """
    from ecoguard.coordinator.packaging import (
        CAUSAL_RULES, angular_gap, bearing_between, distance_km,
        downwind_cells, travel_bearing, wind_direction_at,
    )
    from ecoguard.shared.cells import cell_by_id, service_area_cells

    rule = CAUSAL_RULES[(FIRE, AIR_POLLUTION)]
    direction = wind_direction_at(cell_id, at)
    if direction is None:
        return None
    cone = downwind_cells(cell_id, at, rule)
    if not cone:
        return None

    origin = cell_by_id(cell_id)
    carried = travel_bearing(direction)
    upwind = [
        c.cell_id for c in service_area_cells()
        if c.cell_id != cell_id
        and distance_km(origin.latitude, origin.longitude, c.latitude, c.longitude) <= rule.max_km
        and angular_gap(
            bearing_between(origin.latitude, origin.longitude, c.latitude, c.longitude),
            carried,
        ) > 135
    ]
    if not upwind:
        return None
    return cone[0][0], upwind[0]


def test_pollution_downwind_of_a_fire_becomes_one_hybrid_incident(clean, database):
    at = _weather_hour(database)
    origin = _windy_cell(at)
    assert origin is not None, "no cell has both stored wind and room either side"
    split = _wind_split(origin, at)
    downwind_cell, _ = split

    result = coordinate([
        _signal(origin, at=at, hazard=FIRE),
        _signal(downwind_cell, at=at + timedelta(hours=1),
                hazard=AIR_POLLUTION, variable="pm25"),
    ], at=at + timedelta(hours=1))

    assert len(result.linked) == 1, "the plume should have joined the fire"
    hybrid = store.incident_by_id(result.created[0])
    # One incident, two hazards, both queues — requirement 3 and 4 together.
    assert set(hybrid["hazards"]) == {FIRE, AIR_POLLUTION}
    assert set(hybrid["queues"]) == {EMERGENCY, NON_EMERGENCY}
    assert len(result.emergency) == 1
    assert len(result.non_emergency) == 1
    assert result.emergency[0]["id"] == result.non_emergency[0]["id"]


def test_pollution_upwind_of_a_fire_stays_its_own_incident(clean, database):
    at = _weather_hour(database)
    origin = _windy_cell(at)
    assert origin is not None, "no cell has both stored wind and room either side"
    split = _wind_split(origin, at)
    _, upwind_cell = split

    result = coordinate([
        _signal(origin, at=at, hazard=FIRE),
        _signal(upwind_cell, at=at + timedelta(hours=1),
                hazard=AIR_POLLUTION, variable="pm25"),
    ], at=at + timedelta(hours=1))

    # Same hazards, same distance, same lag — only the bearing differs. Smoke
    # does not travel into the wind, so this is a separate source.
    assert result.linked == []
    assert len(result.emergency) == 1
    assert len(result.non_emergency) == 1
    assert result.emergency[0]["id"] != result.non_emergency[0]["id"]


def test_a_merged_incident_records_why(clean, database):
    at = _weather_hour(database)
    origin = _windy_cell(at)
    assert origin is not None, "no cell has both stored wind and room either side"
    split = _wind_split(origin, at)
    downwind_cell, _ = split

    result = coordinate([
        _signal(origin, at=at, hazard=FIRE),
        _signal(downwind_cell, at=at + timedelta(hours=1),
                hazard=AIR_POLLUTION, variable="pm25"),
    ], at=at + timedelta(hours=1))

    # A merge nobody can account for is one nobody can correct.
    link = store.incident_by_id(result.created[0])["links"][0]
    assert link["cause_hazard"] == FIRE
    assert link["effect_hazard"] == AIR_POLLUTION
    assert "downwind on bearing" in link["rationale"]
    assert link["distance_km"] > 0
