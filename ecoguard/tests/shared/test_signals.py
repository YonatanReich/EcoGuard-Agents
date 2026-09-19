"""The properties that make one hazard's anomaly comparable to another's.

The whole point of this contract is that a coordinator can weigh a brightness
claim against a PM2.5 claim without knowing what either measures. That only
holds if rarity really is on one scale, which means three things must be true
and are each easy to get silently wrong:

Direction must be per hazard *and* variable. Heavy rain is the flood signal and
the absence of the fire signal; one shared table would report every storm as a
fire risk.

Low-is-bad variables must come out near 1 at their bad end. Defaulting every
variable to high-is-bad inverts humidity, soil moisture and greenness, and
"unusually green vegetation" becomes a fire anomaly.

Categorical sources must land on the same scale as continuous ones, or a
satellite hotspot cannot be weighed against a rainfall reading at all.
"""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.shared.signals import (
    AIR_POLLUTION,
    CORROBORATION_WINDOW,
    EITHER,
    FIRE,
    FIRE_WEATHER,
    FLOOD,
    HIGH,
    LOW,
    REPORTING_RARITY,
    Baseline,
    CellSignal,
    corroborates,
    direction_for,
    percentile_of,
    rarity_from_baseline,
    rarity_from_rate,
)

WHEN = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

# A September-noon temperature bucket, shaped like the real ones.
TEMPERATURE = Baseline(
    minimum=25.0, p05=28.8, p25=30.0, median=31.2, p75=33.0, p95=35.2,
    maximum=44.1, samples=300, origin="10y climatology",
)
# Precipitation: dry in almost every hour, which makes every quantile zero.
RAIN = Baseline(
    minimum=0.0, p05=0.0, p25=0.0, median=0.0, p75=0.0, p95=0.0,
    maximum=12.0, samples=300, origin="10y climatology",
)


def _signal(**overrides):
    base = dict(
        cell_id="risk-05000m-r0040-c0020", observed_at=WHEN, hazard=FIRE,
        variable="temperature_2m", value=41.0, unit="C", source="weather",
        rarity=0.98, direction=HIGH,
    )
    return CellSignal(**{**base, **overrides})


# --- placing a reading on its baseline -------------------------------------

def test_the_median_sits_in_the_middle():
    assert percentile_of(TEMPERATURE.median, TEMPERATURE) == pytest.approx(0.5)


def test_percentiles_land_where_they_are_named():
    assert percentile_of(TEMPERATURE.p05, TEMPERATURE) == pytest.approx(0.05)
    assert percentile_of(TEMPERATURE.p95, TEMPERATURE) == pytest.approx(0.95)


def test_readings_beyond_the_record_saturate_rather_than_extrapolate():
    # A decade of samples says nothing about how much worse than its own record
    # a cell can get, so 50 C and 500 C are both simply "off the end".
    assert percentile_of(50.0, TEMPERATURE) == 1.0
    assert percentile_of(500.0, TEMPERATURE) == 1.0
    assert percentile_of(-40.0, TEMPERATURE) == 0.0


def test_placement_is_monotone():
    places = [percentile_of(v, TEMPERATURE) for v in range(20, 50)]
    assert places == sorted(places)


# --- rarity, and the direction that makes it comparable --------------------

def test_a_hot_reading_is_rare_for_fire():
    assert rarity_from_baseline(41.0, TEMPERATURE, HIGH) > 0.95


def test_a_typical_reading_is_not_rare():
    assert rarity_from_baseline(TEMPERATURE.median, TEMPERATURE, HIGH) == pytest.approx(0.5)


def test_low_is_bad_variables_are_rare_at_the_bottom():
    # The inversion this guards: with a default HIGH direction, bone-dry
    # humidity would score 0.05 — "utterly typical" — and the single most
    # reliable fire-weather signal would never fire.
    humidity = Baseline(minimum=5.0, p05=12.0, p25=25.0, median=40.0,
                        p75=55.0, p95=70.0, maximum=98.0, samples=300)

    assert rarity_from_baseline(8.0, humidity, LOW) > 0.95
    assert rarity_from_baseline(90.0, humidity, LOW) < 0.05


def test_either_direction_is_rare_at_both_ends():
    assert rarity_from_baseline(TEMPERATURE.minimum, TEMPERATURE, EITHER) == pytest.approx(1.0)
    assert rarity_from_baseline(TEMPERATURE.maximum, TEMPERATURE, EITHER) == pytest.approx(1.0)
    assert rarity_from_baseline(TEMPERATURE.median, TEMPERATURE, EITHER) == pytest.approx(0.0)


def test_rarity_is_always_a_fraction():
    for value in (-100.0, 0.0, 31.2, 44.1, 1000.0):
        for direction in (HIGH, LOW, EITHER):
            assert 0.0 <= rarity_from_baseline(value, TEMPERATURE, direction) <= 1.0


def test_an_unknown_direction_is_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        rarity_from_baseline(41.0, TEMPERATURE, "sideways")


# --- the degenerate distribution that is precipitation ---------------------

def test_a_dry_hour_in_a_dry_bucket_is_utterly_ordinary():
    # Every quantile is zero because it does not rain in most hours. A dry
    # reading must not come out rare, or the flood detector reports every
    # rainless hour in the country.
    assert rarity_from_baseline(0.0, RAIN, HIGH) == 0.0


def test_any_rain_at_all_is_rare_where_rain_is_rare():
    assert rarity_from_baseline(3.0, RAIN, HIGH) > 0.9
    assert rarity_from_baseline(12.0, RAIN, HIGH) == 1.0


# --- categorical sources join the same scale -------------------------------

def test_a_detection_in_a_cell_that_always_detects_is_unremarkable():
    # A quarry tripping the sensor on two days in five, tripping it again.
    assert rarity_from_rate(0.4) == pytest.approx(0.6)


def test_a_detection_in_a_cell_that_never_detects_is_a_one_off():
    assert rarity_from_rate(0.0) == pytest.approx(1.0)


def test_rate_rarity_shares_the_scale_with_baseline_rarity():
    # The unification: a first-ever hotspot and an all-time-record temperature
    # are both 1.0, so a coordinator can weigh them against each other without
    # knowing that one is kelvin and the other is a yes.
    assert rarity_from_rate(0.0) == rarity_from_baseline(50.0, TEMPERATURE, HIGH)


# --- direction table -------------------------------------------------------

def test_rain_points_opposite_ways_for_flood_and_fire_weather():
    # The reason the table is keyed by both. One shared direction per variable
    # would make every storm a fire signal.
    assert direction_for(FLOOD, "precipitation") == HIGH
    assert direction_for(FIRE_WEATHER, "precipitation") == LOW


def test_an_undeclared_variable_has_no_direction_rather_than_a_default():
    # Forces a deliberate decision per variable instead of silently assuming
    # that big numbers are the bad ones.
    assert direction_for(AIR_POLLUTION, "pollen_count") is None


def test_greenness_and_dryness_are_declared_low():
    assert direction_for(FIRE_WEATHER, "ndvi") == LOW
    assert direction_for(FIRE_WEATHER, "soil_moisture_0_to_7cm") == LOW
    assert direction_for(FIRE_WEATHER, "relative_humidity_2m") == LOW


def test_burning_and_the_conditions_for_burning_are_different_hazards():
    """FIRE is combustion measured; FIRE_WEATHER is the conditions for it.

    Keeping them apart is what stops a dry afternoon being routed to the queue
    that rolls an engine — and the tables have to agree, or a detector would
    ask for a direction that does not exist and raise mid-sweep.
    """
    assert direction_for(FIRE, "frp") == HIGH
    assert direction_for(FIRE, "temperature_2m") is None
    assert direction_for(FIRE_WEATHER, "temperature_2m") == HIGH
    assert direction_for(FIRE_WEATHER, "frp") is None


# --- the signal record -----------------------------------------------------

def test_reporting_needs_a_rarity_not_merely_the_absence_of_one():
    # "Not assessed" must never read as "assessed and fine".
    assert _signal(rarity=None).reportable is False
    assert _signal(rarity=REPORTING_RARITY).reportable is True
    assert _signal(rarity=0.99).reportable is False


def test_beyond_record_needs_a_baseline_to_be_beyond():
    assert _signal(baseline=None).beyond_record is False
    assert _signal(value=50.0, baseline=TEMPERATURE).beyond_record is True
    assert _signal(value=31.0, baseline=TEMPERATURE).beyond_record is False


def test_severity_is_absent_until_an_analyser_fills_it():
    # Detectors answer "how unusual", never "how dangerous".
    assert _signal().severity is None


# --- corroboration ---------------------------------------------------------

def test_two_sources_on_one_cell_corroborate():
    satellite = _signal(source="firms", variable="brightness")
    # Generic signal correlation remains valid, but EA-374 deliberately does
    # not model Telegram evidence as an independently coordinatable CellSignal.
    ground = _signal(source="ground_sensor", variable="report", observed_at=WHEN + timedelta(hours=1))

    assert corroborates(satellite, ground)


def test_an_adjacent_cell_still_corroborates():
    # Events do not respect cell edges. Requiring an exact match is the most
    # common way a deduplicator splits one fire into two incidents.
    here = _signal(cell_id="risk-05000m-r0040-c0020")
    next_door = _signal(cell_id="risk-05000m-r0041-c0021")

    assert corroborates(here, next_door)


def test_a_distant_cell_does_not():
    assert not corroborates(
        _signal(cell_id="risk-05000m-r0040-c0020"),
        _signal(cell_id="risk-05000m-r0060-c0020"),
    )


def test_different_hazards_never_corroborate():
    assert not corroborates(_signal(hazard=FIRE), _signal(hazard=FLOOD))


def test_signals_too_far_apart_in_time_do_not():
    late = _signal(observed_at=WHEN + CORROBORATION_WINDOW + timedelta(minutes=1))

    assert not corroborates(_signal(), late)


def test_the_window_covers_the_satellite_lag():
    # FIRMS near-real-time runs about three hours behind the overpass, so a
    # ground report and its satellite confirmation are routinely hours apart.
    assert CORROBORATION_WINDOW >= timedelta(hours=3)


def test_weak_signals_are_still_allowed_to_agree():
    # Two unreportable signals agreeing is itself evidence. Filtering each on
    # its own before checking agreement discards exactly the corroboration the
    # coordinator exists to find.
    weak = _signal(rarity=0.5)
    other = _signal(rarity=0.5, source="firms")

    assert weak.reportable is False
    assert corroborates(weak, other)


# --- where the thing actually is -------------------------------------------

from ecoguard.shared.signals import (  # noqa: E402
    CELL_ONLY_M,
    LOCALITY_M,
    VIIRS_PIXEL_M,
    CellLocation,
    best_location,
    cell_centre_location,
    locate_points,
)


def test_a_single_pixel_keeps_its_own_coordinates():
    # The fix must be the pixel, not the cell centroid — those sit up to 3.5 km
    # apart and the centroid is on ground that may not be burning.
    fix = locate_points([(33.24898, 35.65257, 9.11)])

    assert fix.latitude == pytest.approx(33.24898)
    assert fix.longitude == pytest.approx(35.65257)
    assert fix.precision_m == pytest.approx(VIIRS_PIXEL_M)


def test_the_fix_is_pulled_toward_the_hottest_pixel():
    # Weighted by radiative power, so the fix lands on the part of the burn a
    # crew heads for rather than the geometric middle of the detections.
    cold_end, hot_end = 32.000, 32.020
    fix = locate_points([(cold_end, 35.0, 1.0), (hot_end, 35.0, 99.0)])

    assert fix.latitude > (cold_end + hot_end) / 2
    assert fix.latitude == pytest.approx(hot_end, abs=0.001)


def test_scattered_pixels_widen_the_precision():
    # Four pixels strung over two kilometres is a two-kilometre fire. Reporting
    # its centroid to 375 m would be a confident fix on a spot between them.
    tight = locate_points([(32.0, 35.0, 1.0), (32.001, 35.001, 1.0)])
    spread = locate_points([(32.0, 35.0, 1.0), (32.02, 35.02, 1.0)])

    assert spread.precision_m > tight.precision_m
    assert spread.precision_m > 1000


def test_unweighted_points_fall_back_to_a_plain_centroid():
    fix = locate_points([(32.0, 35.0, 0.0), (32.02, 35.0, 0.0)])

    assert fix.latitude == pytest.approx(32.01)


def test_no_points_is_no_location():
    assert locate_points([]) is None


def test_a_cell_only_fix_is_not_drawable_as_a_point():
    # A Telegram report naming no street: the cell really is all we know, and
    # a dot would claim precision that does not exist.
    fix = cell_centre_location("risk-05000m-r0085-c0027")

    assert fix.precision_m == CELL_ONLY_M
    assert fix.is_point is False
    assert fix.method == "cell_centre"


def test_a_satellite_fix_is_drawable_as_a_point():
    assert locate_points([(33.24, 35.65, 9.11)]).is_point is True


def test_merging_keeps_the_best_fix_rather_than_averaging():
    # A satellite pixel and a town-name geocode of one fire average to a place
    # neither source suggested, and averaging a 375 m fix with a 2 km one
    # throws the 375 m fix away.
    satellite = CellLocation(33.24898, 35.65257, VIIRS_PIXEL_M, "viirs_pixel")
    town = CellLocation(33.30, 35.70, LOCALITY_M, "locality_geocode")

    assert best_location(satellite, town) is satellite
    assert best_location(town, satellite) is satellite


def test_merging_ignores_the_missing_ones():
    fix = CellLocation(33.2, 35.6, VIIRS_PIXEL_M, "viirs_pixel")

    assert best_location(None, fix, None) is fix
    assert best_location(None, None) is None


def test_a_signal_may_honestly_have_no_location():
    # Must stay distinguishable from a confident fix at the cell centre.
    assert _signal().location is None
