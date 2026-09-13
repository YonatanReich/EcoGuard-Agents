"""Gap detection decides what the collector fetches, so it is what gets tested.

If `missing_hours` under-reports, an hour is lost permanently — that is the
exact failure the fixed lookback window used to cause. If it over-reports, the
collector re-fetches data it already has and walks back into the rate limit.

The rows live in 2020, far from anything the running collectors write, so the
counts these assert against are only ever the test's own.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from ecoguard.database.repositories.weather_history import (
    contiguous_ranges,
    current_for_point,
    hourly_for_cells,
    missing_hours,
)

UTC = timezone.utc
BASE = datetime(2020, 3, 1, 0, tzinfo=UTC)
CELLS = ["test-wh-a", "test-wh-b"]


def at(offset: int) -> datetime:
    return BASE + timedelta(hours=offset)


@pytest.fixture
def store(database):
    """Insert weather observations for the test cells, then remove them."""
    def write(cell_id, hours, *, latitude=31.5, longitude=35.0, temperature=20.0):
        with database.begin() as connection:
            for hour in hours:
                connection.execute(
                    text(
                        """
                        INSERT INTO observations
                          (source, cell_id, location, observed_at, ingested_at, payload)
                        VALUES ('weather', :cell_id,
                                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                                :observed_at, now(), CAST(:payload AS jsonb))
                        ON CONFLICT ON CONSTRAINT observations_identity DO NOTHING
                        """
                    ),
                    {
                        "cell_id": cell_id, "observed_at": hour,
                        "latitude": latitude, "longitude": longitude,
                        "payload": '{"temperature_2m": %s, "relative_humidity_2m": 50.0,'
                                   ' "precipitation": 0.0, "rain": 0.0, "wind_speed_10m": 5.0,'
                                   ' "wind_direction_10m": 180.0, "wind_gusts_10m": 9.0,'
                                   ' "weather_code": 1}' % temperature,
                    },
                )

    yield write

    with database.begin() as connection:
        connection.execute(
            text("DELETE FROM observations WHERE source='weather' AND cell_id = ANY(:ids)"),
            {"ids": CELLS},
        )


# --- gap detection ----------------------------------------------------------

def test_an_hour_stored_for_every_cell_is_not_reported_missing(store):
    for cell in CELLS:
        store(cell, [at(0), at(1)])

    assert missing_hours(CELLS, at(0), at(1)) == {}


def test_an_hour_absent_everywhere_is_reported_for_every_cell(store):
    for cell in CELLS:
        store(cell, [at(0), at(2)])

    assert missing_hours(CELLS, at(0), at(2)) == {cell: [at(1)] for cell in CELLS}


def test_an_hour_stored_for_only_some_cells_is_resolved_per_cell(store):
    # The slow path. An hour is normally written for the whole grid in one
    # batch, but a run that died mid-sweep leaves exactly this, and reporting
    # it complete would strand the cells that missed out.
    store(CELLS[0], [at(0), at(1)])
    store(CELLS[1], [at(0)])

    assert missing_hours(CELLS, at(0), at(1)) == {CELLS[1]: [at(1)]}


def test_an_empty_window_reports_every_hour_for_every_cell(store):
    gaps = missing_hours(CELLS, at(0), at(3))

    assert gaps == {cell: [at(0), at(1), at(2), at(3)] for cell in CELLS}


# --- request shaping --------------------------------------------------------

def test_consecutive_hours_collapse_and_holes_split():
    assert contiguous_ranges([at(1), at(2), at(3), at(7), at(8)]) == [
        (at(1), at(3)), (at(7), at(8)),
    ]


def test_ranges_of_nothing_are_nothing():
    assert contiguous_ranges([]) == []


# --- the model's feature window --------------------------------------------

def test_a_full_window_reads_as_success_in_the_shape_compute_features_wants(store):
    store(CELLS[0], [at(0), at(1), at(2)], temperature=21.5)

    result = hourly_for_cells([CELLS[0]], at(0), at(2))[CELLS[0]]

    assert result["status"] == "success"
    assert result["missing_hours"] == 0
    assert result["hourly"]["temperature_2m"] == [21.5, 21.5, 21.5]
    # Naive ISO text: compute_features attaches UTC itself, and an offset in
    # the string would be applied twice.
    assert result["hourly"]["time"][0] == "2020-03-01T00:00:00"


def test_a_window_with_a_hole_reads_as_partial_rather_than_success(store):
    store(CELLS[0], [at(0), at(2)])

    result = hourly_for_cells([CELLS[0]], at(0), at(2))[CELLS[0]]

    assert result["status"] == "partial"
    assert result["missing_hours"] == 1


def test_a_cell_with_nothing_stored_still_gets_an_entry(store):
    result = hourly_for_cells(CELLS, at(0), at(2))

    assert set(result) == set(CELLS)
    assert all(entry["status"] == "partial" for entry in result.values())
    assert all(entry["hourly"]["time"] == [] for entry in result.values())


# --- point reads ------------------------------------------------------------
#
# Positioned over Cyprus, well outside ISRAEL_RISK_BOUNDS. The national grid is
# collected continuously, so a test that asserts "nothing is near here" has to
# stand somewhere the real collector never writes.

FAR_LATITUDE, FAR_LONGITUDE = 35.00, 33.20


def test_a_point_is_answered_by_the_nearest_cell_with_its_distance(store):
    # current_for_point only accepts recent readings, so these are written at
    # the current hour rather than in 2020 with the rest.
    recent = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    store(CELLS[0], [recent], latitude=FAR_LATITUDE, longitude=FAR_LONGITUDE)
    store(CELLS[1], [recent], latitude=FAR_LATITUDE + 0.02, longitude=FAR_LONGITUDE + 0.02)

    reading = current_for_point(FAR_LATITUDE + 0.001, FAR_LONGITUDE + 0.001)

    assert reading is not None
    assert reading["cell_id"] == CELLS[0]
    assert reading["distance_m"] < 500
    assert reading["temperature_2m"] == 20.0
    assert reading["weather_code"] == 1.0


def test_a_point_beyond_the_cell_reach_returns_nothing(store):
    recent = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    store(CELLS[0], [recent], latitude=FAR_LATITUDE, longitude=FAR_LONGITUDE)

    # A degree of latitude north: ~111 km, far past CELL_REACH_M.
    assert current_for_point(FAR_LATITUDE + 1.0, FAR_LONGITUDE) is None


def test_a_stale_reading_is_not_served_as_current(store):
    # Stored in 2020. The reading exists and is the nearest one there is, and
    # it is still not an answer to "what is it doing now".
    store(CELLS[0], [at(0)], latitude=FAR_LATITUDE, longitude=FAR_LONGITUDE)

    assert current_for_point(FAR_LATITUDE, FAR_LONGITUDE) is None
