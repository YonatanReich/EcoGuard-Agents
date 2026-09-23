"""The FWI system is an accumulator, and accumulators fail quietly.

A wrong FFMC is visible — it moves every day and a bad one looks bad. A wrong
DC is not: it drifts slowly in the right direction and stays plausible for a
season, which is exactly long enough to train a model on it.

So these check the properties that define the system rather than transcribed
outputs. Drying raises the codes, rain lowers them, each code responds on its
own timescale, and the chain is order-dependent — the same week of weather in a
different order must not produce the same state, because that would mean the
memory is not there at all.
"""

import math

import pytest

from ecoguard.collectors.fire.fwi.index import (
    DANGER_CLASSES,
    STARTUP_DC,
    STARTUP_FFMC,
    FireWeatherState,
    advance,
)

# A hot, dry, breezy day: the conditions the whole system exists to describe.
DRY = {"temperature_c": 33.0, "humidity_percent": 15.0, "wind_speed_kmh": 25.0, "rain_24h_mm": 0.0}
WET = {"temperature_c": 18.0, "humidity_percent": 90.0, "wind_speed_kmh": 5.0, "rain_24h_mm": 20.0}


def _run(days, state=None, month=8):
    for day in days:
        state = advance(state, month=month, **day)
    return state


def test_a_dry_day_dries_the_fine_fuels():
    state = advance(None, month=8, **DRY)

    assert state.ffmc > STARTUP_FFMC
    assert state.fwi > 0


def test_rain_wets_the_fine_fuels_again():
    dry = _run([DRY] * 5)
    wet = advance(dry, month=8, **WET)

    assert wet.ffmc < dry.ffmc
    assert wet.fwi < dry.fwi


def test_the_codes_respond_on_their_own_timescales():
    # One dry day after rain: fine fuels recover almost fully, the deep code
    # barely notices. That separation is the entire reason three codes exist
    # instead of one, and collapsing them is the easiest way to get this wrong.
    wet = _run([WET] * 3)
    dry = advance(wet, month=8, **DRY)

    fine = (dry.ffmc - wet.ffmc) / max(wet.ffmc, 1e-9)
    deep = (dry.dc - wet.dc) / max(wet.dc, 1e-9)
    assert fine > deep


def test_drought_accumulates_over_a_season():
    # DC is the months-long memory: a long dry run must keep climbing, not
    # settle at an equilibrium the way FFMC does.
    short = _run([DRY] * 10)
    long = _run([DRY] * 60)

    assert long.dc > short.dc * 2
    # FFMC by contrast saturates - it cannot exceed 101 by definition.
    assert short.ffmc == pytest.approx(long.ffmc, abs=1.0)
    assert long.ffmc <= 101.0


def test_history_order_changes_the_outcome():
    # The property that proves state is actually carried. If these matched, the
    # codes would be a function of the day alone and the memory would be gone.
    rain_first = _run([WET, WET, DRY, DRY, DRY, DRY])
    rain_last = _run([DRY, DRY, DRY, DRY, WET, WET])

    assert rain_first.dc != pytest.approx(rain_last.dc)
    assert rain_first.ffmc > rain_last.ffmc


def test_a_resumed_chain_matches_an_unbroken_one():
    # Storing a state and carrying on from it must be identical to never having
    # stopped, or every collector restart introduces a step change.
    unbroken = _run([DRY] * 6)

    halfway = _run([DRY] * 3)
    resumed = FireWeatherState(
        ffmc=halfway.ffmc, dmc=halfway.dmc, dc=halfway.dc,
        isi=halfway.isi, bui=halfway.bui, fwi=halfway.fwi,
    )
    continued = _run([DRY] * 3, state=resumed)

    assert continued.fwi == pytest.approx(unbroken.fwi)
    assert continued.dc == pytest.approx(unbroken.dc)


def test_wind_raises_spread_without_touching_the_moisture_codes():
    calm = advance(None, month=8, **{**DRY, "wind_speed_kmh": 2.0})
    gale = advance(None, month=8, **{**DRY, "wind_speed_kmh": 60.0})

    assert gale.isi > calm.isi
    assert gale.fwi > calm.fwi
    # Wind dries fine fuels a little, but must not reach the deep codes at all.
    assert gale.dc == pytest.approx(calm.dc)
    assert gale.dmc == pytest.approx(calm.dmc)


def test_every_code_stays_in_its_defined_range():
    state = _run([DRY] * 120)

    assert 0.0 <= state.ffmc <= 101.0
    assert state.dmc >= 0.0 and state.dc >= 0.0
    assert state.isi >= 0.0 and state.bui >= 0.0 and state.fwi >= 0.0
    assert all(math.isfinite(value) for value in
               (state.ffmc, state.dmc, state.dc, state.isi, state.bui, state.fwi))


def test_extreme_weather_reaches_the_top_danger_class():
    assert _run([DRY] * 45).danger_class == "extreme"


def test_a_cold_wet_start_is_not_dangerous():
    assert _run([WET] * 5, month=1).danger_class in {"very_low", "low"}


def test_danger_classes_are_ordered_and_total():
    bounds = [bound for bound, _ in DANGER_CLASSES]

    assert bounds == sorted(bounds)
    assert bounds[-1] == math.inf  # nothing can fall off the end


def test_a_startup_state_is_used_when_there_is_nothing_to_resume():
    # First run of a fresh database: no previous row, so the standard spring
    # values seed the chain rather than zeros, which would read as saturated.
    neutral = advance(None, month=4, temperature_c=20.0, humidity_percent=45.0,
                      wind_speed_kmh=10.0, rain_24h_mm=0.0)

    assert neutral.dc > STARTUP_DC
    assert 0.0 < neutral.ffmc <= 101.0


def test_an_impossible_month_is_refused():
    with pytest.raises(ValueError):
        advance(None, month=13, **DRY)
