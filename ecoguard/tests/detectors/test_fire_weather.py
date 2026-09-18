"""What the fire-weather sweep must not do quietly.

Every test here guards a failure that produces no error and no empty result -
just a wrong number of signals, in a direction nobody would think to check.

The precipitation case is the one worth the most care, because it is not
hypothetical: the September baseline really is zero at every quantile, the
rarity arithmetic really does turn a dry hour into 1.0, and the result would
have been every cell in the country reporting fire weather every hour. A test
that only asserted "dry weather is reported" would have passed on it.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from ecoguard.detectors.fire import weather
from ecoguard.shared.signals import LOW, Baseline, rarity_from_baseline

# February at 03:00 UTC. Nothing real is stored in this bucket - the collected
# history is autumn - so these rows cannot collide with production data, and a
# stray row of ours cannot be mistaken for one.
WHEN = datetime(2026, 2, 10, 3, 0, tzinfo=timezone.utc)

# A bucket a reading has to be genuinely extreme to escape: a decade of
# February nights sitting between 17% and 94% humidity.
HUMID = dict(minimum=17.0, p05=29.0, p25=53.0, median=74.0, p75=81.0, p95=87.0,
             maximum=94.0)
# Every quantile at zero, which is what a real dry-season precipitation bucket
# looks like and what makes rarity meaningless there.
BONE_DRY = dict(minimum=0.0, p05=0.0, p25=0.0, median=0.0, p75=0.0, p95=0.0,
                maximum=0.0)


@pytest.fixture
def cell(database):
    """A real cell that a real baseline answers for, plus its baseline cell.

    Taken from the grid rather than invented: the cell-to-baseline mapping is
    arithmetic over actual coordinates, so a made-up cell id maps to nothing
    and the sweep would skip it for the wrong reason.
    """
    mapping = weather._baseline_cells()
    if not mapping:
        pytest.skip("no weather baselines loaded")
    cell_id = sorted(mapping)[0]
    return cell_id, mapping[cell_id]


@pytest.fixture
def clean(database):
    """Borrow the February 03:00 bucket, and put back whatever was in it.

    These tests have to control the distribution the detector reads, and the
    only way to do that is to occupy a (month, hour) bucket that the real
    table already fills - the climatology covers all 288 of them.

    So the real rows are lifted out, held, and put back afterwards. An earlier
    version of this fixture just deleted them and moved on, which quietly
    destroyed 250 rows of real ten-year climatology that only a full rebuild
    could regenerate. Test isolation must never be paid for out of the data.
    """
    columns = (
        "cell_id, variable, month, hour, samples, mean, std, median, mad, "
        "p05, p25, p75, p95, minimum, maximum"
    )

    with database.connect() as connection:
        borrowed = [
            dict(row)
            for row in connection.execute(
                text(f"SELECT {columns} FROM weather_baselines "
                     "WHERE month = 2 AND hour = 3")
            ).mappings().all()
        ]

    def _clear():
        with database.connect() as connection:
            connection.execute(
                text("DELETE FROM observations WHERE observed_at = :when"),
                {"when": WHEN},
            )
            connection.execute(
                text("DELETE FROM weather_baselines WHERE month = 2 AND hour = 3")
            )
            connection.commit()

    _clear()
    try:
        yield
    finally:
        _clear()
        if borrowed:
            placeholders = ", ".join(f":{name.strip()}" for name in columns.split(","))
            with database.connect() as connection:
                connection.execute(
                    text(f"INSERT INTO weather_baselines ({columns}) "
                         f"VALUES ({placeholders})"),
                    borrowed,
                )
                connection.commit()


def _store_baseline(database, baseline_cell, variable, quantiles):
    with database.connect() as connection:
        connection.execute(
            text(
                """
                INSERT INTO weather_baselines
                  (cell_id, variable, month, hour, samples, mean, std,
                   median, mad, p05, p25, p75, p95, minimum, maximum)
                VALUES
                  (:cell_id, :variable, 2, 3, 300, :median, 1.0,
                   :median, 1.0, :p05, :p25, :p75, :p95, :minimum, :maximum)
                """
            ),
            {"cell_id": baseline_cell, "variable": variable, **quantiles},
        )
        connection.commit()


def _store_reading(database, cell_id, payload, *, at=WHEN, issued_at=None):
    with database.connect() as connection:
        connection.execute(
            text(
                """
                INSERT INTO observations
                  (source, cell_id, observed_at, ingested_at, issued_at, payload)
                VALUES ('weather', :cell_id, :at, :at, :issued_at, :payload)
                """
            ),
            {"cell_id": cell_id, "at": at, "issued_at": issued_at,
             "payload": __import__("json").dumps(payload)},
        )
        connection.commit()


# --- the reason precipitation is excluded ----------------------------------

def test_a_dry_hour_scores_maximum_rarity_against_a_dry_baseline():
    """The arithmetic that would have flooded the queue, pinned in place.

    Not a test of the detector - a test of the claim the detector's exclusion
    list rests on. If this ever stops being true, the exclusion can be revisited
    rather than carried forever as folklore.
    """
    baseline = Baseline(samples=300, origin="test", **BONE_DRY)
    assert rarity_from_baseline(0.0, baseline, LOW) == 1.0


def test_precipitation_is_never_assessed(database, clean, cell):
    """An ordinary rainless hour must produce nothing at all."""
    cell_id, baseline_cell = cell
    _store_baseline(database, baseline_cell, "precipitation", BONE_DRY)
    _store_baseline(database, baseline_cell, "relative_humidity_2m", HUMID)
    _store_reading(database, cell_id, {"precipitation": 0.0,
                                       "relative_humidity_2m": 74.0})

    assert weather.detect(at=WHEN) == []


# --- what it does report ---------------------------------------------------

def test_air_drier_than_the_record_is_reported(database, clean, cell):
    cell_id, baseline_cell = cell
    _store_baseline(database, baseline_cell, "relative_humidity_2m", HUMID)
    _store_reading(database, cell_id, {"relative_humidity_2m": 16.0})

    signals = weather.detect(at=WHEN)

    assert [s.variable for s in signals] == ["relative_humidity_2m"]
    assert signals[0].cell_id == cell_id
    assert signals[0].rarity == 1.0
    # The rarity is a floor, not an estimate: the baseline has never seen this.
    assert signals[0].beyond_record


def test_an_ordinary_hour_is_not_reported(database, clean, cell):
    """The median of the distribution is, by definition, unremarkable."""
    cell_id, baseline_cell = cell
    _store_baseline(database, baseline_cell, "relative_humidity_2m", HUMID)
    _store_reading(database, cell_id, {"relative_humidity_2m": 74.0})

    assert weather.detect(at=WHEN) == []


def test_humidity_is_read_from_the_low_end(database, clean, cell):
    """Direction is what stops a muggy night being reported as fire weather.

    The same distance from the median, on the wrong side. Without the LOW
    direction this would score identically to the dry case.
    """
    cell_id, baseline_cell = cell
    _store_baseline(database, baseline_cell, "relative_humidity_2m", HUMID)
    _store_reading(database, cell_id, {"relative_humidity_2m": 94.0})

    assert weather.detect(at=WHEN) == []


# --- what it must refuse to read -------------------------------------------

def test_a_forecast_is_never_detected_on(database, clean, cell):
    """Forecasts share the table and are marked by issued_at.

    Detecting on one opens an incident for weather that has not happened.
    """
    cell_id, baseline_cell = cell
    _store_baseline(database, baseline_cell, "relative_humidity_2m", HUMID)
    _store_reading(database, cell_id, {"relative_humidity_2m": 16.0},
                   issued_at=WHEN - timedelta(hours=6))

    assert weather.detect(at=WHEN) == []


def test_a_stale_reading_is_not_evidence_about_now(database, clean, cell):
    """Past MAX_AGE the sweep reports nothing rather than reporting old news."""
    cell_id, baseline_cell = cell
    _store_baseline(database, baseline_cell, "relative_humidity_2m", HUMID)
    _store_reading(database, cell_id, {"relative_humidity_2m": 16.0})

    assert weather.detect(at=WHEN + weather.MAX_AGE + timedelta(minutes=1)) == []
    # ...and is still found just inside the window, so this is the age test and
    # not an accidentally broken query.
    assert weather.detect(at=WHEN + weather.MAX_AGE)


def test_a_missing_variable_is_skipped_not_guessed(database, clean, cell):
    """A payload without the variable must not become a zero reading.

    Zero humidity would be the rarest thing the baseline has ever seen.
    """
    cell_id, baseline_cell = cell
    _store_baseline(database, baseline_cell, "relative_humidity_2m", HUMID)
    _store_reading(database, cell_id, {"temperature_2m": 12.0})

    assert weather.detect(at=WHEN) == []


# --- the contract the coordinator consumes ---------------------------------

def test_signals_carry_their_baseline_and_no_invented_location(database, clean, cell):
    """Weather is a field over a cell, not a point in it.

    A centroid here would be drawn as a confident fix on something 25 square
    kilometres wide.
    """
    cell_id, baseline_cell = cell
    _store_baseline(database, baseline_cell, "relative_humidity_2m", HUMID)
    _store_reading(database, cell_id, {"relative_humidity_2m": 16.0})

    signal = weather.detect(at=WHEN)[0]

    assert signal.location is None
    assert signal.severity is None, "severity is the analysers' job"
    assert signal.baseline is not None and signal.baseline.samples == 300
    assert signal.evidence["baseline_cell"] == baseline_cell
    assert signal.unit == "%"
