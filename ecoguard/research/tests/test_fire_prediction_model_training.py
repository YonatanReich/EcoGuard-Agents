import csv
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pytest

from research.training.train_fire_prediction_models import (
    FORBIDDEN_FEATURES,
    ML_FEATURES,
    TrainingError,
    assert_feature_allowlist,
    calculate_metrics,
    fit_and_compare,
    load_dataset,
    matrix,
    select_threshold,
    temporal_split,
    train_and_evaluate,
)


def raw_row(identifier, timestamp, label, value, mapped=True):
    row = {
        "sample_id": identifier,
        "sample_type": "positive" if label else "negative",
        "timestamp": timestamp,
        "latitude": "31.9",
        "longitude": "34.9",
        "settlement": "רמלה" if mapped else "",
        "settlement_lamas_code": "8500" if mapped else "",
        "fire_label": str(label),
        "label_source": "test",
        "weather_collection_status": "success",
    }
    row.update({feature: str(value + index / 100) for index, feature in enumerate(ML_FEATURES)})
    return row


def normalized_row(identifier, timestamp, label, value, mapped=True):
    row = raw_row(identifier, timestamp, label, value, mapped)
    row["_timestamp"] = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    row["_label"] = label
    row["_features"] = [float(row[feature]) for feature in ML_FEATURES]
    return row


def write_dataset(path: Path, rows):
    fields = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def small_dataset_rows():
    rows = []
    counter = 0
    for year, count in ((2023, 12), (2024, 12), (2025, 12), (2026, 12)):
        for index in range(count):
            label = index % 2
            value = label * 2 + index / 20
            rows.append(
                raw_row(
                    f"sample-{counter}",
                    f"{year}-06-{index + 1:02d}T10:00:00Z",
                    label,
                    value,
                    mapped=not (year == 2026 and index < 3),
                )
            )
            counter += 1
    return rows


def test_exact_temporal_split_and_no_overlap():
    rows = [
        normalized_row("a", "2023-01-01T00:00:00Z", 0, 0),
        normalized_row("b", "2024-12-31T23:00:00Z", 1, 1),
        normalized_row("c", "2025-01-01T00:00:00Z", 0, 0),
        normalized_row("d", "2025-12-31T23:00:00Z", 1, 1),
        normalized_row("e", "2026-01-01T00:00:00Z", 0, 0),
        normalized_row("f", "2026-06-01T00:00:00Z", 1, 1),
    ]
    splits = temporal_split(rows)
    assert {row["_timestamp"].year for row in splits["train"]} == {2023, 2024}
    assert {row["_timestamp"].year for row in splits["validation"]} == {2025}
    assert {row["_timestamp"].year for row in splits["test"]} == {2026}
    assert max(row["_timestamp"] for row in splits["train"]) < min(row["_timestamp"] for row in splits["validation"])
    assert max(row["_timestamp"] for row in splits["validation"]) < min(row["_timestamp"] for row in splits["test"])


def test_feature_allowlist_and_leakage_rejection():
    assert assert_feature_allowlist(ML_FEATURES) == ML_FEATURES
    assert not (set(ML_FEATURES) & FORBIDDEN_FEATURES)
    with pytest.raises(TrainingError, match="allowlist"):
        assert_feature_allowlist(ML_FEATURES + ("latitude",))
    with pytest.raises(TrainingError, match="allowlist"):
        assert_feature_allowlist(tuple(reversed(ML_FEATURES)))


def test_scaler_is_fit_only_on_training_values():
    train_x = np.ones((20, len(ML_FEATURES)))
    train_y = np.asarray([0, 1] * 10)
    validation_x = np.full((10, len(ML_FEATURES)), 100.0)
    validation_y = np.asarray([0, 1] * 5)
    _, _, models, _ = fit_and_compare(train_x, train_y, validation_x, validation_y)
    scaler = models["logistic_regression"].named_steps["scaler"]
    assert np.allclose(scaler.mean_, 1.0)


def test_deterministic_training():
    rng = np.random.default_rng(4)
    train_x = rng.normal(size=(40, len(ML_FEATURES)))
    train_y = np.asarray([0, 1] * 20)
    validation_x = rng.normal(size=(20, len(ML_FEATURES)))
    validation_y = np.asarray([0, 1] * 10)
    first = fit_and_compare(train_x, train_y, validation_x, validation_y, seed=17)
    second = fit_and_compare(train_x, train_y, validation_x, validation_y, seed=17)
    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[3] == second[3]


def test_threshold_selection_uses_only_supplied_validation_arrays():
    labels = np.asarray([0, 0, 1, 1])
    probabilities = np.asarray([0.1, 0.4, 0.6, 0.9])
    threshold, metrics = select_threshold(labels, probabilities)
    assert threshold == pytest.approx(0.5)
    assert metrics["f1"] == 1.0
    # There is deliberately no test-set argument to threshold selection.
    assert select_threshold(labels, probabilities) == (threshold, metrics)


def test_metrics_calculation():
    labels = np.asarray([0, 0, 1, 1])
    probabilities = np.asarray([0.1, 0.8, 0.4, 0.9])
    metrics = calculate_metrics(labels, probabilities, 0.5)
    assert metrics["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert metrics["accuracy"] == 0.5
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["predicted_positive_rate"] == 0.5
    assert metrics["positive_prevalence"] == 0.5


def test_model_serialization_and_prediction_feature_ordering(tmp_path):
    dataset = tmp_path / "dataset.csv"
    output = tmp_path / "ml"
    write_dataset(dataset, small_dataset_rows())
    metrics = train_and_evaluate(
        dataset_path=dataset,
        output_directory=output,
        seed=23,
        creation_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    bundle = joblib.load(output / "fire_prediction_model.joblib")
    assert bundle["metadata"]["feature_names"] == list(ML_FEATURES)
    assert bundle["metadata"]["threshold"] == metrics["selected_threshold"]
    rows = load_dataset(dataset)
    splits = temporal_split(rows)
    test_x, _ = matrix(splits["test"])
    probabilities = bundle["pipeline"].predict_proba(test_x)[:, 1]
    assert len(probabilities) == len(splits["test"])
    assert (output / "fire_prediction_metrics.json").exists()
    assert (output / "fire_prediction_feature_importance.csv").exists()
    assert (output / "fire_prediction_test_predictions.csv").exists()
