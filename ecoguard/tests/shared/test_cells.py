"""The cell has to be the same place for everyone, or nothing above it works.

Three properties carry the whole design.

Ids must resolve to ground with no lookup, because a quarter of a million
stored rows reference them and the mapping has to survive the database being
empty.

`cell_for` must invert `generate_grid` exactly. If the two disagree even at the
edges, a station and a satellite pixel standing on the same ground get
different cells and the coordinator sees two events where there is one.

Adjacency must include the cell itself, because every caller asking "same
place?" means "here or next door", and a predicate that excludes the equality
case gets it wrong at exactly the moment it matters.
"""

import pytest

from ecoguard.shared.cells import (
    are_adjacent,
    bounds_of,
    cell_by_id,
    cell_for,
    is_cell_id,
    neighbours,
    parse_cell_id,
    service_area_cells,
)

SAMPLE = "risk-05000m-r0002-c0013"


# --- ids ------------------------------------------------------------------

def test_an_id_parses_to_its_resolution_row_and_column():
    assert parse_cell_id(SAMPLE) == (5000, 2, 13)


def test_a_telegram_identity_is_not_a_place():
    # observations.cell_id holds `channel:message_id` for telegram, because
    # nothing knows where a message refers to until extraction runs. Any query
    # joining cell_id to geography must be able to tell them apart.
    assert parse_cell_id("fire_alerts_il:4821") is None
    assert is_cell_id("fire_alerts_il:4821") is False
    assert is_cell_id(SAMPLE) is True


def test_parsing_does_not_require_the_cell_to_be_collected():
    # What an id *means* and whether we collect there are different questions.
    assert parse_cell_id("risk-05000m-r9999-c9999") == (5000, 9999, 9999)
    assert cell_by_id("risk-05000m-r9999-c9999") is None


# --- the round trip that everything depends on -----------------------------

def test_every_cell_centre_resolves_back_to_its_own_cell():
    # The invariant: cell_for inverts generate_grid. A drift here means two
    # sources standing on one patch of ground disagree about where they are.
    for cell in service_area_cells():
        assert cell_for(cell.latitude, cell.longitude) == cell.cell_id


def test_a_point_outside_the_service_area_has_no_cell():
    assert cell_for(48.86, 2.35) is None      # Paris
    assert cell_for(0.0, 0.0) is None         # Gulf of Guinea


def test_cell_by_id_and_cell_for_agree():
    cell = service_area_cells()[len(service_area_cells()) // 2]

    assert cell_by_id(cell.cell_id) == cell
    assert cell_for(cell.latitude, cell.longitude) == cell.cell_id


# --- geometry --------------------------------------------------------------

def test_a_cell_contains_its_own_centre():
    cell = cell_by_id(SAMPLE)
    west, south, east, north = bounds_of(SAMPLE)

    assert west < cell.longitude < east
    assert south < cell.latitude < north


def test_cells_are_square_on_the_ground_not_in_degrees():
    # The longitude step is recomputed per row so a cell is 5 km wide at Eilat
    # and at Metula. In degrees the northern one is visibly wider.
    southern = min(service_area_cells(), key=lambda c: c.latitude)
    northern = max(service_area_cells(), key=lambda c: c.latitude)

    south_west, _, south_east, _ = bounds_of(southern.cell_id)
    north_west, _, north_east, _ = bounds_of(northern.cell_id)

    assert (north_east - north_west) > (south_east - south_west)


def test_a_non_cell_id_has_no_bounds():
    assert bounds_of("fire_alerts_il:4821") is None


# --- adjacency, which is what corroboration rests on -----------------------

def test_a_cell_is_adjacent_to_itself():
    # Every caller means "here or next door". Excluding the equality case is
    # how a deduplicator fails on the most common input it gets.
    assert are_adjacent(SAMPLE, SAMPLE) is True


def test_neighbours_exclude_the_cell_itself():
    assert SAMPLE not in neighbours(SAMPLE)


def test_an_interior_cell_has_eight_neighbours():
    interior = next(
        cell.cell_id for cell in service_area_cells()
        if len(neighbours(cell.cell_id)) == 8
    )

    assert len(neighbours(interior)) == 8
    assert all(are_adjacent(interior, other) for other in neighbours(interior))


def test_an_edge_cell_simply_has_fewer():
    # Never ids that do not exist — an edge cell has fewer neighbours rather
    # than neighbours outside the service area.
    counts = {len(neighbours(cell.cell_id)) for cell in service_area_cells()}

    assert counts - {8}, "some cell must sit on an edge"
    assert max(counts) == 8
    assert all(cell_by_id(n) is not None
               for cell in service_area_cells()[:50]
               for n in neighbours(cell.cell_id))


def test_adjacency_is_symmetric():
    for other in neighbours(SAMPLE):
        assert are_adjacent(SAMPLE, other) == are_adjacent(other, SAMPLE)


def test_a_wider_radius_reaches_further():
    assert len(neighbours(SAMPLE, radius=2)) > len(neighbours(SAMPLE, radius=1))


def test_non_cell_ids_are_never_adjacent_to_anything():
    assert are_adjacent("fire_alerts_il:4821", SAMPLE) is False
    assert neighbours("fire_alerts_il:4821") == ()
