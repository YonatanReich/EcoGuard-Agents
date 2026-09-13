"""Train the richer temporal wildfire baseline and lightweight ablations."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.inspection import permutation_importance

from ecoguard.research.datasets.build_historical_environmental_features import (
    FIRE_HISTORY_FEATURES,
    SEASON_FEATURES,
    TOPOGRAPHY_FEATURES,
)
from ecoguard.research.datasets.build_historical_fire_weather_features import FEATURE_FIELDS
from ecoguard.research.training.train_fire_prediction_models import (
    FORBIDDEN_FEATURES,
    RANDOM_SEED,
    calculate_metrics,
    feature_rankings,
    fit_and_compare,
    geographic_audit,
    parse_timestamp,
    split_counts,
    temporal_split,
)
from ecoguard.paths import GENERATED


DATASET_PATH = GENERATED / "fire_prediction_ml_environmental_dataset_2023_2026.csv"
BASELINE_METRICS_PATH = GENERATED / "ml" / "fire_prediction_metrics.json"
OUTPUT_DIRECTORY = GENERATED / "ml"
MODEL_NAME = "fire_prediction_environmental_model.joblib"
METRICS_NAME = "fire_prediction_environmental_metrics.json"
IMPORTANCE_NAME = "fire_prediction_environmental_feature_importance.csv"
PREDICTIONS_NAME = "fire_prediction_environmental_test_predictions.csv"

WEATHER_FEATURES = tuple(FEATURE_FIELDS)
FULL_FEATURES = WEATHER_FEATURES + SEASON_FEATURES + TOPOGRAPHY_FEATURES + FIRE_HISTORY_FEATURES
ABLATIONS = {
    "weather_only": WEATHER_FEATURES,
    "weather_plus_season": WEATHER_FEATURES + SEASON_FEATURES,
    "weather_plus_topography": WEATHER_FEATURES + TOPOGRAPHY_FEATURES,
    "weather_plus_fire_history": WEATHER_FEATURES + FIRE_HISTORY_FEATURES,
    "full": FULL_FEATURES,
}


class EnvironmentalTrainingError(RuntimeError): pass


def assert_environmental_features(features=FULL_FEATURES):
    leaked = set(features) & FORBIDDEN_FEATURES
    if leaked: raise EnvironmentalTrainingError(f"forbidden features: {sorted(leaked)}")
    if len(features) != len(set(features)): raise EnvironmentalTrainingError("duplicate features")
    return tuple(features)


def load_environmental_dataset(path: Path = DATASET_PATH):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"sample_id", "timestamp", "fire_label", *FULL_FEATURES}.issubset(rows[0]):
        raise EnvironmentalTrainingError("environmental dataset schema is incompatible")
    assert_environmental_features()
    output = []
    for row in rows:
        values = {}
        for field in FULL_FEATURES:
            value = row.get(field)
            values[field] = float(value) if value not in {None, ""} else np.nan
        output.append({**row, "_timestamp": parse_timestamp(row["timestamp"]), "_label": int(row["fire_label"]), "_environmental": values})
    return sorted(output, key=lambda row: (row["_timestamp"], row["sample_id"]))


def matrix_for(rows, features):
    return np.asarray([[row["_environmental"][field] for field in features] for row in rows], dtype=float), np.asarray([row["_label"] for row in rows], dtype=int)


def distribution_shift(splits):
    result = {}
    for feature in FULL_FEATURES:
        values = {name: np.asarray([row["_environmental"][feature] for row in rows], dtype=float) for name, rows in splits.items()}
        medians = {name: float(np.nanmedian(data)) for name, data in values.items()}
        train_std = float(np.nanstd(values["train"]))
        result[feature] = {"median": medians, "train_to_test_standardized_median_difference": (medians["test"] - medians["train"]) / train_std if train_std else 0.0}
    return result


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"); temporary.replace(path)


def _write_csv(path, fields, rows):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def train_environmental(*, dataset_path=DATASET_PATH, baseline_metrics_path=BASELINE_METRICS_PATH, output_directory=OUTPUT_DIRECTORY, seed=RANDOM_SEED, creation_time=None):
    rows = load_environmental_dataset(dataset_path); splits = temporal_split(rows)
    ablations = {}; fitted = {}
    for group, features in ABLATIONS.items():
        train_x, train_y = matrix_for(splits["train"], features); val_x, val_y = matrix_for(splits["validation"], features); test_x, test_y = matrix_for(splits["test"], features)
        model_name, threshold, models, validation = fit_and_compare(train_x, train_y, val_x, val_y, seed=seed)
        probabilities = models[model_name].predict_proba(test_x)[:, 1]
        ablations[group] = {"features": list(features), "selected_model": model_name, "threshold": threshold, "validation_models": validation, "validation": validation[model_name], "test": {"threshold_0_50": calculate_metrics(test_y, probabilities, 0.5), "selected_threshold": calculate_metrics(test_y, probabilities, threshold)}}
        fitted[group] = (models, probabilities, threshold)
    models, probabilities, threshold = fitted["full"]; selected_name = ablations["full"]["selected_model"]; selected = models[selected_name]
    baseline = json.loads(baseline_metrics_path.read_text(encoding="utf-8"))
    shift = distribution_shift(splits)
    metadata = {"feature_names": list(FULL_FEATURES), "selected_model_type": selected_name, "threshold": threshold, "train_years": [2023, 2024], "validation_year": 2025, "test_year": 2026, "random_seed": seed, "sklearn_version": sklearn.__version__, "creation_timestamp": (creation_time or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"), "dataset_path": str(dataset_path)}
    validation_x, validation_y = matrix_for(splits["validation"], FULL_FEATURES)
    permutation = permutation_importance(
        selected,
        validation_x,
        validation_y,
        scoring="average_precision",
        n_repeats=5,
        random_state=seed,
        n_jobs=1,
    )
    selected_rankings = [
        {
            "model": selected_name,
            "importance_type": "validation_permutation_average_precision",
            "rank": rank,
            "feature": FULL_FEATURES[index],
            "value": float(permutation.importances_mean[index]),
            "absolute_value": abs(float(permutation.importances_mean[index])),
            "direction": "",
        }
        for rank, index in enumerate(np.argsort(permutation.importances_mean)[::-1], start=1)
    ]
    metrics = {"metadata": metadata, "split_counts": split_counts(splits), "distribution_shift": shift, "ablations": ablations, "weather_only_previous_baseline": baseline["test_metrics"], "full_validation_model_comparison": ablations["full"]["validation_models"], "full_test": ablations["full"]["test"], "test_geography_audit": geographic_audit(splits["test"], probabilities, threshold), "selected_model_feature_importance": selected_rankings}
    output_directory.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": selected, "metadata": metadata}, output_directory / MODEL_NAME)
    _write_json(output_directory / METRICS_NAME, metrics)
    rankings = selected_rankings + feature_rankings(models, FULL_FEATURES)
    _write_csv(output_directory / IMPORTANCE_NAME, tuple(rankings[0]), rankings)
    labels = (probabilities >= threshold).astype(int)
    prediction_rows = [{"sample_id": row["sample_id"], "timestamp": row["timestamp"], "fire_label": row["_label"], "predicted_probability": float(probability), "predicted_label": int(label), "sample_type": row["sample_type"], "location_status": "mapped" if row.get("settlement_lamas_code") else "unlocated"} for row, probability, label in zip(splits["test"], probabilities, labels)]
    _write_csv(output_directory / PREDICTIONS_NAME, tuple(prediction_rows[0]), prediction_rows)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--dataset", type=Path, default=DATASET_PATH); parser.add_argument("--baseline-metrics", type=Path, default=BASELINE_METRICS_PATH); parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY); args = parser.parse_args()
    metrics = train_environmental(dataset_path=args.dataset, baseline_metrics_path=args.baseline_metrics, output_directory=args.output_dir)
    print(json.dumps(metrics, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
