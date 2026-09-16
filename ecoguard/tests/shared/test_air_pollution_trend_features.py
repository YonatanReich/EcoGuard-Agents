from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ecoguard.shared.air_pollution_history import (
    AirPollutionSeriesIdentity,
    HistoricalAirPollutionObservation,
)
from ecoguard.shared.air_pollution_trend_features import (
    PROVIDER_TIMEZONE,
    ResearchSplitPolicy,
    build_causal_features,
    build_target,
    estimate_training_stability_band,
)

IDENTITY = AirPollutionSeriesIdentity("1", "4", "NO2")
START = datetime(2023, 6, 1, 12, 0, tzinfo=PROVIDER_TIMEZONE)


def observation(minutes, value, identity=IDENTITY):
    return HistoricalAirPollutionObservation(
        identity=identity,
        observed_at=START + timedelta(minutes=minutes),
        value=value,
        unit="µg/m³",
        provider_unit="µg/m³",
    )


def test_features_are_causal_and_exact_lags_expose_gaps():
    history = [observation(-10, -2), observation(-5, -1), observation(0, 1), observation(5, 999)]
    features = build_causal_features(history, START)
    changed_future = build_causal_features(history[:-1] + [observation(5, -999)], START)
    assert features == changed_future
    assert features["current_concentration"] == 1
    assert features["lag_5m"] == -1
    assert features["lag_10m"] == -2
    assert features["lag_15m"] is None and features["lag_15m_missing"] == 1
    assert features["minutes_since_previous_valid"] == 5
    assert features["valid_count_15m"] == 3
    assert features["coverage_ratio_15m"] == 1
    assert features["slope_15m_per_minute"] == pytest.approx(0.3)


def test_target_uses_available_25_30_35_minute_values_only():
    history = [observation(0, 10), observation(25, 12), observation(35, 16), observation(32, 1000)]
    target = build_target(history, START)
    assert target is not None
    assert target.future_concentration == 14
    assert target.delta_30 == 4
    assert target.contributing_offsets_minutes == (25, 35)
    assert build_target([observation(0, 10), observation(30, 12)], START) is None


def test_split_embargo_and_window_boundaries_are_enforced():
    policy = ResearchSplitPolicy()
    boundary = datetime(2024, 1, 1, tzinfo=PROVIDER_TIMEZONE)
    assert policy.split_for_example(boundary - timedelta(minutes=156)) == ("train", None)
    assert policy.split_for_example(boundary - timedelta(minutes=100))[1] == "split_embargo"
    assert policy.split_for_example(boundary + timedelta(minutes=100))[1] == "split_embargo"
    assert policy.split_for_example(boundary + timedelta(minutes=156)) == ("validation", None)


def test_epsilon_estimator_uses_training_period_only_and_retains_negatives():
    training = [observation(0, -2), observation(5, -1), observation(10, 2), observation(15, 7)]
    validation_outlier = observation(220000, 1_000_000)
    kwargs = {
        "training_start": START,
        "training_end": START + timedelta(minutes=20),
        "scale_multiplier": 1.0,
    }
    first = estimate_training_stability_band("NO2", {IDENTITY: training}, **kwargs)
    second = estimate_training_stability_band(
        "NO2", {IDENTITY: training + [validation_outlier]}, **kwargs
    )
    assert first == second
    assert first.epsilon == 2
    assert first.authoritative_instrument_uncertainty is False
    assert first.label(-2) == "STABLE"
    assert first.label(-2.1) == "FALLING"
