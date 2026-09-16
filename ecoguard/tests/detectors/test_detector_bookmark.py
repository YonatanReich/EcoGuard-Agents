"""The bookmark: what a detector sees when it wakes up.

A detector that asks "what happened in the last six hours" loses everything
older than six hours whenever it is not running, and logs nothing about it. For
a fire detector that is the one unacceptable failure - the fire simply never
existed as far as the system is concerned.

So the question a detector asks is "what arrived since I last finished", and
these tests pin both halves of that:

  * a long outage costs latency and nothing else
  * a row already processed is not processed again

The second is the cheaper failure by far, which is why the design leans on it:
the read happens *after* the run is logged, so anything ingested mid-read is
seen twice rather than never. Duplicates are the coordinator's job. Gaps are
nobody's.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from ecoguard.database.repositories.collector_runs import last_success_at
from ecoguard.detectors.fire import satellite
from ecoguard.shared.cells import service_area_cells

NOW = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def clean(database):
    """Remove only what these tests write."""
    def _purge():
        with database.connect() as connection:
            connection.execute(
                text("DELETE FROM observations WHERE source = 'firms' "
                     "AND observed_at BETWEEN :a AND :b"),
                {"a": NOW - timedelta(days=3), "b": NOW + timedelta(days=3)},
            )
            connection.execute(
                text("DELETE FROM collector_runs WHERE source = :s"),
                {"s": satellite.RUN_SOURCE},
            )
            connection.commit()
    _purge()
    yield
    _purge()


def _store(database, cell_id, observed_at, ingested_at, frp=25.0):
    cell = next(c for c in service_area_cells() if c.cell_id == cell_id)
    payload = {
        "hotspots": [{
            "latitude": cell.latitude, "longitude": cell.longitude, "frp": frp,
            "confidence": "n", "firms_source": "VIIRS_SNPP_NRT",
            "instrument": "VIIRS",
            "acquisition_date": observed_at.date().isoformat(),
            "acquisition_time": observed_at.strftime("%H%M"),
        }],
        "hotspot_count": 1, "peak_frp_mw": frp,
        "satellite_sources": ["VIIRS_SNPP_NRT"],
    }
    with database.connect() as connection:
        connection.execute(
            text("INSERT INTO observations "
                 "  (source, cell_id, observed_at, ingested_at, issued_at, payload) "
                 "VALUES ('firms', :cell, :obs, :ing, NULL, :payload)"),
            {"cell": cell_id, "obs": observed_at, "ing": ingested_at,
             "payload": json.dumps(payload)},
        )
        connection.commit()


def _mark(database, started_at, status="ok"):
    """Pretend a run finished then, which is what the bookmark reads."""
    with database.connect() as connection:
        connection.execute(
            text("INSERT INTO collector_runs (source, started_at, finished_at, status) "
                 "VALUES (:s, :t, :t, :st)"),
            {"s": satellite.RUN_SOURCE, "t": started_at, "st": status},
        )
        connection.commit()


@pytest.fixture
def cells():
    grid = service_area_cells()
    return grid[150].cell_id, grid[450].cell_id, grid[750].cell_id


# --- the failure the bookmark exists to prevent ----------------------------

def test_an_outage_longer_than_the_window_loses_nothing(clean, cells, database):
    """Down for eight hours, with a detection in hour one.

    Under a six-hour window that detection is invisible forever and nothing
    says so. Under a bookmark it is simply read late.
    """
    cell, _, _ = cells
    _mark(database, NOW - timedelta(hours=9))
    # Arrived an hour into the outage - well outside MAX_AGE by the time the
    # detector wakes, but after the bookmark.
    arrived = NOW - timedelta(hours=8)
    _store(database, cell, observed_at=arrived, ingested_at=arrived)

    rows = satellite.arrivals_since(last_success_at(satellite.RUN_SOURCE), NOW)

    assert [r["cell_id"] for r in rows] == [cell]
    assert NOW - rows[0]["observed_at"] > satellite.MAX_AGE, (
        "this is precisely the row a window would have dropped"
    )


def test_a_row_already_read_is_not_read_again(clean, cells, database):
    """The bookmark moves past what has been processed."""
    cell, _, _ = cells
    _mark(database, NOW - timedelta(hours=2))
    ingested = NOW - timedelta(hours=1)
    _store(database, cell, observed_at=ingested, ingested_at=ingested)

    first = satellite.arrivals_since(last_success_at(satellite.RUN_SOURCE), NOW)
    assert len(first) == 1

    # A later run, bookmarked after that arrival.
    _mark(database, NOW - timedelta(minutes=30))
    second = satellite.arrivals_since(last_success_at(satellite.RUN_SOURCE), NOW)
    assert second == []


def test_only_arrivals_after_the_bookmark_are_read(clean, cells, database):
    """Ordering is by arrival, not by observation time.

    FIRMS runs hours behind the overpass, so a row stored now can describe an
    earlier moment than one stored yesterday. Sorting the read by `observed_at`
    would make the bookmark meaningless.
    """
    before, after, _ = cells
    _mark(database, NOW - timedelta(hours=3))
    # Observed *later* but ingested before the bookmark: already seen.
    _store(database, before, observed_at=NOW - timedelta(minutes=10),
           ingested_at=NOW - timedelta(hours=4))
    # Observed earlier but ingested after: new.
    _store(database, after, observed_at=NOW - timedelta(hours=2),
           ingested_at=NOW - timedelta(minutes=5))

    rows = satellite.arrivals_since(last_success_at(satellite.RUN_SOURCE), NOW)

    assert [r["cell_id"] for r in rows] == [after]


# --- the bookmark itself ---------------------------------------------------

def test_a_failed_run_does_not_move_the_bookmark(clean, cells, database):
    """A crash must re-read its span, not skip it."""
    _mark(database, NOW - timedelta(hours=5), status="ok")
    _mark(database, NOW - timedelta(hours=1), status="failed")

    assert last_success_at(satellite.RUN_SOURCE) == NOW - timedelta(hours=5)


def test_a_first_run_does_not_swallow_the_whole_table(clean, cells, database):
    """No bookmark yet means recent history, not everything ever stored.

    Otherwise the very first tick after deployment would open an incident for
    every fire in the archive.
    """
    cell, _, _ = cells
    ancient = NOW - timedelta(days=2)
    _store(database, cell, observed_at=ancient, ingested_at=ancient)

    assert last_success_at(satellite.RUN_SOURCE) is None
    assert satellite.arrivals_since(None, NOW) == []


def test_a_backfill_of_old_observations_does_not_raise_incidents(clean, cells, database):
    """Fresh arrival, stale observation: history, not news."""
    cell, _, _ = cells
    _mark(database, NOW - timedelta(hours=2))
    _store(database, cell,
           observed_at=NOW - satellite.STALE_AFTER - timedelta(hours=1),
           ingested_at=NOW - timedelta(minutes=1))

    assert satellite.arrivals_since(last_success_at(satellite.RUN_SOURCE), NOW) == []
