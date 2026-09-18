from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from ecoguard.research.training.evaluate_air_pollution_trend_phase2a import (
    feature_matrix,
    build_year_arrays,
)
from ecoguard.shared.air_pollution_history import (
    AirPollutionSeriesIdentity,
    HistoricalAirPollutionObservation,
)
from ecoguard.shared.air_pollution_trend_features import (
    FEATURE_COLUMNS,
    PROVIDER_TIMEZONE,
    build_causal_features,
)


def _observation(moment, value):
    return HistoricalAirPollutionObservation(
        identity=AirPollutionSeriesIdentity("1", "4", "NO2"),
        observed_at=moment,
        value=value,
        unit="µg/m³",
        provider_unit="µg/m³",
    )


def test_vectorized_features_match_phase1_scalar_features_with_gap():
    anchor = datetime(2022, 6, 1, 12, 0, tzinfo=PROVIDER_TIMEZONE)
    observations = [
        _observation(anchor + timedelta(minutes=offset), float(index - 5))
        for index, offset in enumerate(range(-120, 40, 5))
        if offset not in (-45, -15, 30)
    ]
    arrays = build_year_arrays(observations, 2022)
    year_start = datetime(2022, 1, 1, tzinfo=PROVIDER_TIMEZONE)
    slot = int((anchor - year_start).total_seconds() // 300)
    mask = np.zeros(len(arrays.current_values), dtype=bool)
    mask[slot] = True
    vectorized = feature_matrix(arrays, mask)[0]
    scalar = build_causal_features(observations, anchor)
    for index, name in enumerate(FEATURE_COLUMNS):
        expected = scalar[name]
        if expected is None:
            assert np.isnan(vectorized[index]), name
        else:
            assert vectorized[index] == pytest.approx(expected), name


def test_vectorized_target_requires_two_exact_future_readings():
    anchor = datetime(2022, 6, 1, 12, 0, tzinfo=PROVIDER_TIMEZONE)
    observations = [
        _observation(anchor, 10),
        _observation(anchor + timedelta(minutes=25), 12),
        _observation(anchor + timedelta(minutes=35), 16),
    ]
    arrays = build_year_arrays(observations, 2022)
    start = datetime(2022, 1, 1, tzinfo=PROVIDER_TIMEZONE)
    slot = int((anchor - start).total_seconds() // 300)
    assert arrays.target_eligible[slot]
    assert arrays.target_values[slot] == 14
    assert arrays.deltas[slot] == 4
