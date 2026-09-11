import csv
from datetime import datetime, timezone

import joblib

from research.datasets.build_historical_environmental_features import ENVIRONMENTAL_FEATURES
from research.datasets.build_historical_fire_weather_features import FEATURE_FIELDS
from research.training.train_fire_prediction_environmental_models import (
    ABLATIONS,
    FULL_FEATURES,
    assert_environmental_features,
    load_environmental_dataset,
    matrix_for,
)
from research.training.train_fire_prediction_models import FORBIDDEN_FEATURES, temporal_split


def row(identifier, year, label):
    value = float(label + year / 10000)
    result = {"sample_id": identifier, "sample_type": "positive" if label else "negative", "timestamp": f"{year}-06-01T10:00:00Z", "latitude": "31.9", "longitude": "34.9", "settlement_lamas_code": "8500", "fire_label": str(label)}
    result.update({field: str(value) for field in FEATURE_FIELDS})
    result.update({field: str(value) for field in ENVIRONMENTAL_FEATURES})
    return result


def test_feature_groups_and_forbidden_fields():
    assert assert_environmental_features() == FULL_FEATURES
    assert not (set(FULL_FEATURES) & FORBIDDEN_FEATURES)
    assert ABLATIONS["weather_only"] == tuple(FEATURE_FIELDS)
    assert set(ENVIRONMENTAL_FEATURES).issubset(FULL_FEATURES)


def test_temporal_split_is_unchanged(tmp_path):
    path = tmp_path / "data.csv"
    rows = [row(f"{year}-{label}", year, label) for year in (2023, 2024, 2025, 2026) for label in (0, 1)]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0])); writer.writeheader(); writer.writerows(rows)
    splits = temporal_split(load_environmental_dataset(path))
    assert {item["_timestamp"].year for item in splits["train"]} == {2023, 2024}
    assert {item["_timestamp"].year for item in splits["validation"]} == {2025}
    assert {item["_timestamp"].year for item in splits["test"]} == {2026}
    matrix, labels = matrix_for(splits["train"], FULL_FEATURES)
    assert matrix.shape == (4, len(FULL_FEATURES))
    assert labels.tolist() == [0, 1, 0, 1]


def test_saved_environmental_model_preserves_feature_order():
    bundle = joblib.load("data/generated/ml/fire_prediction_environmental_model.joblib") if __import__("pathlib").Path("data/generated/ml/fire_prediction_environmental_model.joblib").exists() else None
    if bundle is not None:
        assert bundle["metadata"]["feature_names"] == list(FULL_FEATURES)


def test_saved_metrics_preserve_validation_only_model_comparison():
    path = __import__("pathlib").Path("data/generated/ml/fire_prediction_environmental_metrics.json")
    if path.exists():
        metrics = __import__("json").loads(path.read_text(encoding="utf-8"))
        comparison = metrics["full_validation_model_comparison"]
        assert set(comparison) == {
            "dummy",
            "logistic_regression",
            "random_forest",
            "hist_gradient_boosting",
        }
        assert metrics["metadata"]["selected_model_type"] == max(
            comparison,
            key=lambda name: (
                comparison[name]["selected_threshold_metrics"]["pr_auc"],
                comparison[name]["selected_threshold_metrics"]["f1"],
                comparison[name]["selected_threshold_metrics"]["recall"],
                name != "dummy",
            ),
        )
