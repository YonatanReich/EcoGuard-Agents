"""Anomaly scoring, and the skew that breaks the obvious way of doing it.

The failure this guards against is not a wrong threshold. It is using a
mean-and-sigma z-score on a variable that is zero most of the time. Israeli
September precipitation is zero in the overwhelming majority of hours, so the
mean sits just above zero, the standard deviation is dominated by a handful of
storms, and *every* rainy hour scores as unremarkable while some dry ones score
as unusual. Median and MAD do not have that failure, and where MAD collapses to
zero the percentile band still ranks correctly.

The other property tested here is that a baseline does not drift: the whole
point of climatology over a trailing window is that a long heatwave stays
anomalous on day ten, which a self-updating baseline cannot manage.
"""

import numpy as np
import pytest

from ecoguard.database.repositories.climatology import (
    ANOMALY_Z,
    MAX_BASELINE_DISTANCE_KM,
    assess,
    baseline_cell_for,
)
from ecoguard.scripts.build_weather_baselines import (
    MIN_SAMPLES,
    bucket_index,
    summarise,
    vapour_pressure_deficit,
)


def _bucket(values):
    summary = summarise(np.array(values, dtype="float32"))
    assert summary is not None
    return summary


# --- bucketing -------------------------------------------------------------

def test_timestamps_land_in_their_month_and_hour_bucket():
    buckets = bucket_index(["2021-01-01T00:00", "2021-01-01T13:00", "2021-12-31T23:00"])

    assert list(buckets) == [0, 13, 11 * 24 + 23]


def test_the_same_hour_in_different_years_shares_a_bucket():
    # This is what makes a bucket a decade deep instead of a single reading.
    assert bucket_index(["2016-09-14T12:00"])[0] == bucket_index(["2025-09-14T12:00"])[0]


def test_every_month_hour_pair_has_a_distinct_bucket():
    stamps = [f"2021-{m:02d}-01T{h:02d}:00" for m in range(1, 13) for h in range(24)]

    assert len(set(bucket_index(stamps))) == 288


# --- summarising -----------------------------------------------------------

def test_a_thin_bucket_is_dropped_rather_than_stored():
    # A p95 computed from five samples looks exactly as authoritative as one
    # from three hundred, which is how a short fetch becomes a confident lie.
    assert summarise(np.arange(MIN_SAMPLES - 1, dtype="float32")) is None
    assert summarise(np.arange(MIN_SAMPLES, dtype="float32")) is not None


def test_missing_hours_are_excluded_not_counted_as_zero():
    values = np.array([20.0] * MIN_SAMPLES + [np.nan] * 10, dtype="float32")

    summary = summarise(values)

    assert summary["samples"] == MIN_SAMPLES
    assert summary["mean"] == pytest.approx(20.0)


def test_percentiles_are_ordered():
    summary = _bucket(np.random.default_rng(0).normal(28, 4, 500))

    assert summary["minimum"] <= summary["p05"] <= summary["p25"]
    assert summary["p25"] <= summary["median"] <= summary["p75"]
    assert summary["p75"] <= summary["p95"] <= summary["maximum"]


# --- assessment ------------------------------------------------------------

def test_a_typical_reading_is_not_flagged():
    bucket = _bucket(np.random.default_rng(1).normal(28, 3, 500))

    assert assess(28.0, bucket)["anomalous"] is False
    assert assess(28.0, bucket)["band"] == "typical"


def test_a_genuine_extreme_is_flagged():
    bucket = _bucket(np.random.default_rng(2).normal(28, 3, 500))

    verdict = assess(48.0, bucket)

    assert verdict["anomalous"] is True
    assert verdict["band"] == "extremely_high"
    assert abs(verdict["z"]) >= ANOMALY_Z


def test_beyond_record_is_separate_from_anomalous():
    # "Outside anything in ten years" is a stronger statement than "unusual",
    # and a caller escalating on it should not have to infer it from a z-score.
    bucket = _bucket(np.random.default_rng(3).normal(28, 3, 500))

    assert assess(80.0, bucket)["beyond_record"] is True
    assert assess(28.0, bucket)["beyond_record"] is False


def test_precipitation_skew_does_not_break_the_score():
    # 480 dry hours and 20 wet ones — Israeli September. A mean-and-sigma score
    # would rate the wettest hour as barely unusual; rank does not.
    values = [0.0] * 480 + [4.0, 6.0, 9.0, 12.0] * 5
    bucket = _bucket(values)

    assert bucket["mad"] == 0.0  # more than half the bucket is identical
    wet = assess(12.0, bucket)

    assert wet["method"] == "percentile"
    assert wet["z"] is None
    assert wet["anomalous"] is True
    assert wet["band"] == "extremely_high"


def test_a_dry_hour_in_a_dry_bucket_is_unremarkable():
    bucket = _bucket([0.0] * 480 + [4.0, 6.0, 9.0, 12.0] * 5)

    assert assess(0.0, bucket)["anomalous"] is False


def test_the_median_is_reported_so_a_verdict_can_show_its_working():
    bucket = _bucket(np.random.default_rng(4).normal(28, 3, 500))

    verdict = assess(40.0, bucket)

    # A lone boolean is not an explanation; these are what make it one.
    assert {"median", "p05", "p95", "record_low", "record_high", "samples"} <= set(verdict)


def test_a_long_heatwave_stays_anomalous():
    # The property a trailing window cannot have. The baseline is fixed, so the
    # tenth consecutive extreme day scores exactly as the first did — where a
    # self-updating window would by then have absorbed the heatwave as normal.
    bucket = _bucket(np.random.default_rng(5).normal(28, 3, 500))

    first = assess(44.0, bucket)
    tenth = assess(44.0, bucket)

    assert first["z"] == tenth["z"]
    assert tenth["anomalous"] is True


# --- derived variable ------------------------------------------------------

def test_vapour_pressure_deficit_matches_its_definition():
    # 34.4 C at 24% RH is 4.13 kPa by Tetens; the stored forecasts agree.
    value = vapour_pressure_deficit(np.array([34.4]), np.array([24.0]))[0]

    assert value == pytest.approx(4.13, abs=0.02)


def test_saturated_air_has_no_deficit():
    assert vapour_pressure_deficit(np.array([20.0]), np.array([100.0]))[0] == pytest.approx(0.0)


def test_deficit_grows_with_temperature_at_equal_humidity():
    # Why RH alone is not enough: same humidity, very different drying power.
    cool = vapour_pressure_deficit(np.array([15.0]), np.array([25.0]))[0]
    hot = vapour_pressure_deficit(np.array([35.0]), np.array([25.0]))[0]

    assert hot > cool * 3


# --- cell mapping ----------------------------------------------------------

def test_a_baseline_cell_resolves_to_itself():
    from ecoguard.database.repositories.climatology import _baseline_cells

    candidates = _baseline_cells()
    if not candidates:
        pytest.skip("no baselines built")

    # Asking at a baseline cell's own coordinates must return that cell. Phrased
    # against whatever is actually built rather than a fixed landmark, so the
    # test measures the mapping instead of measuring how far the build got.
    cell_id, latitude, longitude = candidates[len(candidates) // 2]
    assert baseline_cell_for(latitude, longitude) == cell_id


def test_a_far_away_baseline_is_refused_rather_than_used():
    # The bug this pins: with only the south built, the Galilee resolved to a
    # Negev cell 200 km away and was handed desert percentiles for a
    # Mediterranean climate. Every field looked well-formed, which is exactly
    # what made it dangerous. Out of range must return None, not "nearest".
    assert baseline_cell_for(0.0, 0.0) is None          # Gulf of Guinea
    assert baseline_cell_for(48.86, 2.35) is None       # Paris


def test_the_distance_ceiling_clears_a_complete_grid():
    # Baselines sit ~15 km apart, so the furthest any cell can be from one is
    # about half a diagonal — 11 km. The ceiling must be above that or a fully
    # built grid would start refusing its own cells.
    assert MAX_BASELINE_DISTANCE_KM > 15.0


def test_an_unreachable_baseline_reports_a_reason_not_an_empty_result():
    from ecoguard.database.repositories.climatology import anomalies

    result = anomalies(48.86, 2.35, month=9, hour=12, readings={"temperature_2m": 20.0})

    # "We could not check" must not be mistakable for "we checked, it is fine".
    assert result["cell_id"] is None
    assert result["assessed"] == {}
    assert result["unavailable"] == ["temperature_2m"]
    assert result["reason"] == "no_baseline_within_range"
