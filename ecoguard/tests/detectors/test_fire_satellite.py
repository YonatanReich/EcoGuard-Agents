"""The satellite detector: can it tell a fire from a factory?

That is the whole job. A hotspot feed with no memory reports the steel works in
the Rishon LeZion industrial belt every night it runs, and an emergency queue
that cries wolf nightly is worse than no queue, because people learn to skim it.
So the suppression tests here are the ones that matter, and they are written
from both sides: the furnace must be silenced, and a cell that has never lit
must get through even when the detection is small and unimpressive.

The second theme is what the signal carries. The coordinator dedupes it and the
analysers price it, and both need more than "there is a fire in cell X" - a real
location to dispatch to, an intensity to model from, and the growth curve that
says whether it is taking hold. Those are asserted here because they are easy to
drop in a refactor and nothing downstream would fail loudly if they went
missing; the incident would simply become less useful.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from ecoguard.detectors.fire import satellite
from ecoguard.shared.cells import cell_by_id, service_area_cells
from ecoguard.shared.signals import (
    FIRE,
    GEOSTATIONARY_PIXEL_M,
    MODIS_PIXEL_M,
    VIIRS_PIXEL_M,
)

WHEN = datetime(2026, 2, 11, 9, 0, tzinfo=timezone.utc)

BASELINE_COLUMNS = (
    "cell_id, days_observed, detection_days, detections, peak_frp_mw, "
    "window_start, window_end"
)


def _pixel(latitude, longitude, frp, *, confidence="n", source="VIIRS_SNPP_NRT"):
    return {
        "latitude": latitude, "longitude": longitude, "frp": frp,
        "confidence": confidence, "firms_source": source, "instrument": "VIIRS",
        "acquisition_date": WHEN.date().isoformat(), "acquisition_time": "0900",
        "satellite": "N", "daynight": "D",
    }


@pytest.fixture
def cells(database):
    """Three real cells, far enough apart not to be adjacent."""
    grid = service_area_cells()
    return grid[100], grid[400], grid[700]


@pytest.fixture
def world(database):
    """Control the rate baseline for the test cells, and give it back after.

    firms_baselines has one row per cell and the real table is fully populated,
    so these rows have to be borrowed rather than merely added - and put back,
    because a deleted baseline silently un-suppresses whatever it was holding
    down.
    """
    def _clear():
        with database.connect() as connection:
            connection.execute(
                text("DELETE FROM observations "
                     "WHERE source = 'firms' AND observed_at BETWEEN :a AND :b"),
                {"a": WHEN - timedelta(days=2), "b": WHEN + timedelta(days=2)},
            )
            connection.commit()

    with database.connect() as connection:
        borrowed = [
            dict(row) for row in connection.execute(
                text(f"SELECT {BASELINE_COLUMNS} FROM firms_baselines")
            ).mappings().all()
        ]
        connection.execute(text("DELETE FROM firms_baselines"))
        connection.commit()

    _clear()
    try:
        yield
    finally:
        _clear()
        with database.connect() as connection:
            connection.execute(text("DELETE FROM firms_baselines"))
            if borrowed:
                placeholders = ", ".join(
                    f":{name.strip()}" for name in BASELINE_COLUMNS.split(",")
                )
                connection.execute(
                    text(f"INSERT INTO firms_baselines ({BASELINE_COLUMNS}) "
                         f"VALUES ({placeholders})"),
                    borrowed,
                )
            connection.commit()


def _set_rate(database, cell_id, detection_days, days_observed=365):
    with database.connect() as connection:
        connection.execute(
            text(f"INSERT INTO firms_baselines ({BASELINE_COLUMNS}) VALUES "
                 "(:cell_id, :days_observed, :detection_days, :detection_days, "
                 " 5.0, '2025-09-16', '2026-09-16')"),
            {"cell_id": cell_id, "days_observed": days_observed,
             "detection_days": detection_days},
        )
        connection.commit()


def _detect_at(database, cell_id, pixels, *, at=WHEN, satellites=None):
    payload = {
        "hotspots": pixels,
        "hotspot_count": len(pixels),
        "peak_frp_mw": max((p["frp"] for p in pixels), default=None),
        "satellite_sources": satellites or sorted({p["firms_source"] for p in pixels}),
    }
    with database.connect() as connection:
        connection.execute(
            text("INSERT INTO observations "
                 "  (source, cell_id, observed_at, ingested_at, issued_at, payload) "
                 "VALUES ('firms', :cell_id, :at, :at, NULL, :payload)"),
            {"cell_id": cell_id, "at": at, "payload": json.dumps(payload)},
        )
        connection.commit()


# --- the whole job ---------------------------------------------------------

def test_a_cell_that_lights_most_nights_is_suppressed(world, cells, database):
    """The furnace. Lit on 292 of 365 days, so tonight means nothing."""
    furnace, _, _ = cells
    cell = cell_by_id(furnace.cell_id)
    _set_rate(database, furnace.cell_id, detection_days=292)
    _detect_at(database, furnace.cell_id,
               [_pixel(cell.latitude, cell.longitude, 1.8)])

    assert satellite.detect(at=WHEN) == []


def test_a_cell_that_has_never_lit_is_reported_even_for_a_small_fire(world, cells, database):
    """The opposite side. A 1.2 MW detection is unimpressive and still news."""
    _, quiet, _ = cells
    cell = cell_by_id(quiet.cell_id)
    _set_rate(database, quiet.cell_id, detection_days=0)
    _detect_at(database, quiet.cell_id,
               [_pixel(cell.latitude, cell.longitude, 1.2)])

    signals = satellite.detect(at=WHEN)

    assert len(signals) == 1
    assert signals[0].rarity == 1.0
    assert signals[0].value == 1.2


def test_one_past_fire_does_not_suppress_the_next(world, cells, database):
    """A cell that burned for three days last year is not an industrial site.

    This is why the bar is persistence rather than REPORTING_RARITY: at 0.999
    a single prior fire-day in the window would silence the cell for a year.
    """
    _, cell_ref, _ = cells
    cell = cell_by_id(cell_ref.cell_id)
    _set_rate(database, cell_ref.cell_id, detection_days=3)
    _detect_at(database, cell_ref.cell_id,
               [_pixel(cell.latitude, cell.longitude, 30.0)])

    assert len(satellite.detect(at=WHEN)) == 1


def test_the_suppression_boundary_is_one_day_in_twenty(world, cells, database):
    """Either side of PERSISTENT_SHARE, with nothing else different."""
    _, under, over = cells
    days = int(365 * satellite.PERSISTENT_SHARE)

    for cell_ref, detection_days in ((under, days - 1), (over, days + 15)):
        cell = cell_by_id(cell_ref.cell_id)
        _set_rate(database, cell_ref.cell_id, detection_days=detection_days)
        _detect_at(database, cell_ref.cell_id,
                   [_pixel(cell.latitude, cell.longitude, 12.0)])

    reported = {s.cell_id for s in satellite.detect(at=WHEN)}
    assert under.cell_id in reported
    assert over.cell_id not in reported


def test_an_unknown_cell_is_reported_not_silently_dropped(world, cells, database):
    """No baseline row means no history, which is not the same as quiet.

    Staying silent about a fire because the backfill has not reached that cell
    is the worst failure available to this detector.
    """
    _, unknown, _ = cells
    cell = cell_by_id(unknown.cell_id)
    _detect_at(database, unknown.cell_id,
               [_pixel(cell.latitude, cell.longitude, 44.0)])

    signals = satellite.detect(at=WHEN)

    assert len(signals) == 1
    assert signals[0].rarity is None, "honest 'not assessed', not a fabricated 1.0"
    assert signals[0].evidence["days_observed"] is None


# --- what the analysers are given ------------------------------------------

def test_the_location_is_the_fire_not_the_cell_centre(world, cells, database):
    """A crew is dispatched to a point. The centroid is FRP-weighted, so it
    lands on the hot end of the burn rather than the middle of the pixels."""
    _, target, _ = cells
    cell = cell_by_id(target.cell_id)
    _set_rate(database, target.cell_id, detection_days=0)
    # Two pixels: a weak one at the cell centre, a fierce one just north.
    _detect_at(database, target.cell_id, [
        _pixel(cell.latitude, cell.longitude, 1.0),
        _pixel(cell.latitude + 0.02, cell.longitude, 99.0),
    ])

    location = satellite.detect(at=WHEN)[0].location

    assert location is not None
    assert location.method == "frp_weighted_centroid"
    assert location.latitude > cell.latitude + 0.015, "pulled toward the hot pixel"
    # Two pixels 2 km apart is a 2 km fire; the precision must say so rather
    # than claiming the 375 m of a single pixel.
    assert location.precision_m > VIIRS_PIXEL_M


def test_a_modis_pixel_never_claims_viirs_precision(world, cells, database):
    """1 km instrument, 1 km floor. Averaging must not invent sharpness."""
    _, target, _ = cells
    cell = cell_by_id(target.cell_id)
    _set_rate(database, target.cell_id, detection_days=0)
    _detect_at(database, target.cell_id,
               [_pixel(cell.latitude, cell.longitude, 8.0, source="MODIS_NRT")])

    assert satellite.detect(at=WHEN)[0].location.precision_m >= MODIS_PIXEL_M


def test_the_growth_curve_travels_with_the_signal(world, cells, database):
    """A spread model that gets one frame is guessing at the term that matters.

    Three overpasses climbing 4.7 -> 18.6 -> 71.6 MW say the fire is taking
    hold; the newest frame alone cannot.
    """
    _, target, _ = cells
    cell = cell_by_id(target.cell_id)
    _set_rate(database, target.cell_id, detection_days=0)
    for offset, frp in ((-2, 4.7), (-1, 18.6), (0, 71.6)):
        _detect_at(database, target.cell_id,
                   [_pixel(cell.latitude, cell.longitude, frp)],
                   at=WHEN + timedelta(hours=offset))

    signals = satellite.detect(at=WHEN)

    assert len(signals) == 1, "three looks at one fire is one signal"
    assert signals[0].value == 71.6, "the newest frame sets the value"
    curve = [entry["peak_frp_mw"] for entry in signals[0].evidence["recent_detections"]]
    assert curve == [4.7, 18.6, 71.6], "oldest first, so a trend is readable"


def test_independent_satellites_raise_confidence(world, cells, database):
    """Glint and hot roofs rarely survive a different look angle at another hour."""
    _, one, two = cells
    for cell_ref, sources in ((one, ["VIIRS_SNPP_NRT"]),
                              (two, ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"])):
        cell = cell_by_id(cell_ref.cell_id)
        _set_rate(database, cell_ref.cell_id, detection_days=0)
        _detect_at(database, cell_ref.cell_id,
                   [_pixel(cell.latitude, cell.longitude, 10.0)],
                   satellites=sources)

    found = {s.cell_id: s.confidence for s in satellite.detect(at=WHEN)}
    assert found[two.cell_id] > found[one.cell_id]


def test_the_signal_is_shaped_for_the_coordinator(world, cells, database):
    """Contract check: what goes downstream, and what deliberately does not."""
    _, target, _ = cells
    cell = cell_by_id(target.cell_id)
    _set_rate(database, target.cell_id, detection_days=0)
    _detect_at(database, target.cell_id,
               [_pixel(cell.latitude, cell.longitude, 22.5)])

    signal = satellite.detect(at=WHEN)[0]

    assert signal.hazard == FIRE
    assert signal.unit == "MW"
    assert signal.source == "firms"
    assert signal.severity is None, "how dangerous is the analysers' question"
    assert signal.evidence["hotspot_count"] == 1
    assert signal.evidence["detection_share"] == 0.0


# --- freshness -------------------------------------------------------------

def test_a_stale_detection_is_not_a_current_fire(world, cells, database):
    _, target, _ = cells
    cell = cell_by_id(target.cell_id)
    _set_rate(database, target.cell_id, detection_days=0)
    _detect_at(database, target.cell_id,
               [_pixel(cell.latitude, cell.longitude, 15.0)])

    assert satellite.detect(at=WHEN + satellite.MAX_AGE + timedelta(minutes=1)) == []
    assert satellite.detect(at=WHEN + satellite.MAX_AGE)


# --- the geostationary product ---------------------------------------------
#
# Meteosat arrives through the same FIRMS pipe under the data_id GOES_NRT, and
# agrees with the polar products about nothing except what a fire is: its
# confidence is a fraction rather than a letter or a percentage, and its pixels
# are kilometres rather than hundreds of metres. Both differences are silent if
# got wrong - a mis-scaled confidence reads as noise, an overstated precision
# sends a crew to the wrong field.

def _geo_pixel(latitude, longitude, frp, confidence="0.94"):
    return {
        "latitude": latitude, "longitude": longitude, "frp": frp,
        "confidence": confidence, "firms_source": "GOES_NRT", "instrument": "",
        "acquisition_date": WHEN.date().isoformat(), "acquisition_time": "0900",
        "satellite": "Met12", "daynight": "D",
    }


def test_meteosat_confidence_is_read_as_a_fraction(world, cells, database):
    """0.94 is near-certainty on this product, not 0.94 percent.

    Dividing by 100 the way MODIS needs would turn the most confident
    detections Meteosat produces into something indistinguishable from noise.
    """
    _, target, _ = cells
    cell = cell_by_id(target.cell_id)
    _set_rate(database, target.cell_id, detection_days=0)
    _detect_at(database, target.cell_id,
               [_geo_pixel(cell.latitude, cell.longitude, 21.0)],
               satellites=["GOES_NRT"])

    assert satellite.detect(at=WHEN)[0].confidence == pytest.approx(0.94)


def test_modis_confidence_is_still_read_as_a_percentage(world, cells, database):
    """The companion to the test above: the scales must not be confused.

    A MODIS "72" and a Meteosat "0.72" are the same claim written two ways, and
    a reader that picks the scale from the number alone gets a MODIS "1" wrong
    by two orders of magnitude.
    """
    _, target, _ = cells
    cell = cell_by_id(target.cell_id)
    _set_rate(database, target.cell_id, detection_days=0)
    _detect_at(database, target.cell_id,
               [_pixel(cell.latitude, cell.longitude, 9.0,
                       confidence="72", source="MODIS_NRT")])

    assert satellite.detect(at=WHEN)[0].confidence == pytest.approx(0.72)


def test_a_geostationary_pixel_never_claims_polar_precision(world, cells, database):
    """Kilometres, not hundreds of metres - and a mixed fix takes the coarsest."""
    _, alone, mixed = cells
    for cell_ref, pixels in (
        (alone, lambda c: [_geo_pixel(c.latitude, c.longitude, 18.0)]),
        (mixed, lambda c: [_geo_pixel(c.latitude, c.longitude, 18.0),
                           _pixel(c.latitude, c.longitude, 20.0)]),
    ):
        cell = cell_by_id(cell_ref.cell_id)
        _set_rate(database, cell_ref.cell_id, detection_days=0)
        _detect_at(database, cell_ref.cell_id, pixels(cell))

    found = {s.cell_id: s.location.precision_m for s in satellite.detect(at=WHEN)}
    assert found[alone.cell_id] >= GEOSTATIONARY_PIXEL_M
    assert found[mixed.cell_id] >= GEOSTATIONARY_PIXEL_M, (
        "one coarse pixel in the mix sets the floor; averaging would invent "
        "sharpness the geostationary instrument never had"
    )
