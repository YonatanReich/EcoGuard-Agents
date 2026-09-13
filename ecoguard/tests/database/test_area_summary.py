"""The area-weighting is the whole accuracy claim, so it is what gets tested.

Counting whole cells whose centroid falls inside the polygon would pass every
"does it return a number" check and still be wrong by a cell on every edge.
These assert the fraction.

Each test measures the *change* a known cell makes to the answer, rather than
the answer itself. population_cells carries no source column to filter a
fixture by, so a test that asserted absolute totals would either have to
truncate a colleague's loaded national grid or be written against whatever
happens to be under the test polygon that week.
"""

import pytest
from sqlalchemy import text

from ecoguard.api.area_schemas import AreaSummaryRequest
from ecoguard.database.repositories.area_summary import summarize_area

# Open ground in the Negev. Any real population underneath cancels out of the
# deltas, so the patch only has to be inside Israel's bounding box.
WEST, SOUTH, EAST, NORTH = 34.90, 30.90, 35.00, 31.00
MIDDLE = (WEST + EAST) / 2


def _polygon(west, south, east, north):
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south],
        ]],
    }


def _population_of(geometry):
    return summarize_area(geometry)["population"]


@pytest.fixture
def add_cell(database):
    """Insert a population cell for the duration of one test, then remove it."""
    written = []

    def insert(west, south, east, north, population):
        with database.begin() as connection:
            written.append(connection.execute(
                text(
                    """
                    INSERT INTO population_cells (cell, population)
                    VALUES (ST_MakeEnvelope(:west, :south, :east, :north, 4326), :population)
                    RETURNING id
                    """
                ),
                {
                    "west": west, "south": south, "east": east, "north": north,
                    "population": population,
                },
            ).scalar_one())

    yield insert

    with database.begin() as connection:
        connection.execute(
            text("DELETE FROM population_cells WHERE id = ANY(:ids)"), {"ids": written}
        )


def test_a_polygon_covering_half_a_cell_counts_half_its_people(add_cell):
    western_half = _polygon(WEST, SOUTH, MIDDLE, NORTH)

    before = _population_of(western_half)
    add_cell(WEST, SOUTH, EAST, NORTH, 1000)
    after = _population_of(western_half)

    # The tolerance is the endpoint's own rounding to whole people, nothing else.
    assert after - before == pytest.approx(500, abs=1)


def test_a_polygon_covering_the_whole_cell_counts_all_of_it(add_cell):
    whole = _polygon(WEST, SOUTH, EAST, NORTH)

    before = _population_of(whole)
    add_cell(WEST, SOUTH, EAST, NORTH, 1000)

    assert _population_of(whole) - before == pytest.approx(1000, abs=1)


def test_a_cell_outside_the_polygon_contributes_nobody(add_cell):
    western_half = _polygon(WEST, SOUTH, MIDDLE, NORTH)

    before = _population_of(western_half)
    add_cell(MIDDLE, SOUTH, EAST, NORTH, 1000)

    assert _population_of(western_half) == before


def test_a_summary_reports_area_in_square_kilometres(database):
    # A tenth of a degree square at latitude 31 is roughly 11.1 km north-south
    # by 9.5 km east-west, so about 106 km2. Degrees squared would read 0.01,
    # and square metres 106 million.
    assert 95 < summarize_area(_polygon(WEST, SOUTH, EAST, NORTH))["area_km2"] < 120


def test_a_self_intersecting_freehand_ring_is_answered_rather_than_rejected(database):
    # A figure-of-eight: what a wobbling hand actually draws. ST_Intersection
    # refuses it outright without the ST_MakeValid in AREA_CTE.
    bowtie = {
        "type": "Polygon",
        "coordinates": [[
            [WEST, SOUTH], [EAST, NORTH], [EAST, SOUTH], [WEST, NORTH], [WEST, SOUTH],
        ]],
    }
    assert summarize_area(bowtie)["area_km2"] > 0


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Point", "coordinates": [35.0, 31.0]},
        {"type": "Polygon", "coordinates": [[[35.0, 31.0], [35.1, 31.0], [35.0, 31.0]]]},
        # Ring left open.
        {"type": "Polygon",
         "coordinates": [[[35.0, 31.0], [35.1, 31.0], [35.1, 31.1], [35.0, 31.1]]]},
        # Cairo: outside the service area.
        _polygon(31.0, 29.8, 31.4, 30.2),
    ],
)
def test_bad_geometry_is_refused_before_it_reaches_postgis(geometry):
    with pytest.raises(ValueError):
        AreaSummaryRequest(geometry=geometry)


def test_a_plain_rectangle_is_accepted():
    assert AreaSummaryRequest(geometry=_polygon(WEST, SOUTH, EAST, NORTH))
