from __future__ import annotations

import numpy as np

from scripts.calibrate_fire_risk_levels import (
    assign_risk_levels,
    bucket_statistics,
    compare_calibration_methods,
    derive_risk_thresholds,
    expected_calibration_error,
)


def test_calibration_comparison_is_deterministic_and_bounded():
    raw = np.linspace(0.03, 0.97, 100)
    labels = np.asarray(([0] * 60) + ([1] * 40))
    first, first_parameters = compare_calibration_methods(raw, labels)
    second, second_parameters = compare_calibration_methods(raw, labels)
    assert first == second
    assert first_parameters == second_parameters
    assert first["selected_method"] in {"raw", "sigmoid", "isotonic"}
    assert len(first["out_of_fold_scores"]) == len(labels)


def test_thresholds_are_derived_from_supplied_validation_data_only():
    scores = np.linspace(0.01, 0.99, 200)
    labels = np.asarray(([0] * 120) + ([1] * 80))
    low, high, details = derive_risk_thresholds(scores, labels)
    assert 0 < low < high < 1
    assert details["high_validation_alert_rate"] <= 0.30
    assert details["medium_or_high_validation_recall"] >= 0.90


def test_risk_level_boundary_behavior():
    levels = assign_risk_levels([0.19, 0.20, 0.69, 0.70], 0.20, 0.70)
    assert levels.tolist() == ["low", "medium", "medium", "high"]


def test_bucket_statistics_reports_monotonicity_without_hiding_failure():
    monotonic = bucket_statistics([0, 0, 1, 1, 1, 1], [0.1, 0.2, 0.4, 0.5, 0.8, 0.9], 0.3, 0.7)
    non_monotonic = bucket_statistics([1, 0, 0], [0.1, 0.5, 0.9], 0.3, 0.7)
    assert monotonic["monotonic_positive_prevalence"] is True
    assert non_monotonic["monotonic_positive_prevalence"] is False


def test_expected_calibration_error_is_zero_for_matching_bins():
    assert expected_calibration_error([0, 1], [0.0, 1.0]) == 0.0
