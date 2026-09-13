"""Evaluate land-cover and terrain additions using the established temporal method."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.inspection import permutation_importance

from research.datasets.build_historical_landcover_terrain_features import LAND_COVER_FEATURES, TERRAIN_FEATURES
from research.training.train_fire_prediction_environmental_models import FULL_FEATURES as CURRENT_FEATURES
from research.training.train_fire_prediction_environmental_models import matrix_for
from research.training.train_fire_prediction_models import (
    FORBIDDEN_FEATURES, RANDOM_SEED, calculate_metrics, fit_and_compare,
    geographic_audit, parse_timestamp, split_counts, temporal_split,
)
from ecoguard.paths import GENERATED


DATASET_PATH = GENERATED / "fire_prediction_ml_landcover_terrain_dataset_2023_2026.csv"
OUTPUT_DIRECTORY = GENERATED / "ml"
MODEL_NAME = "fire_prediction_landcover_terrain_model.joblib"
METRICS_NAME = "fire_prediction_landcover_terrain_metrics.json"
IMPORTANCE_NAME = "fire_prediction_landcover_terrain_feature_importance.csv"
PREDICTIONS_NAME = "fire_prediction_landcover_terrain_test_predictions.csv"
FULL_FEATURES = CURRENT_FEATURES + LAND_COVER_FEATURES + TERRAIN_FEATURES
ABLATIONS = {
    "current_enriched": CURRENT_FEATURES,
    "current_plus_land_cover": CURRENT_FEATURES + LAND_COVER_FEATURES,
    "current_plus_slope": CURRENT_FEATURES + TERRAIN_FEATURES,
    "current_plus_land_cover_and_slope": FULL_FEATURES,
}


class LandcoverTerrainTrainingError(RuntimeError): pass


def assert_feature_allowlist(features=FULL_FEATURES):
    leaked = set(features) & FORBIDDEN_FEATURES
    if leaked: raise LandcoverTerrainTrainingError(f"forbidden features: {sorted(leaked)}")
    if len(features) != len(set(features)): raise LandcoverTerrainTrainingError("duplicate model features")
    return tuple(features)


def load_dataset(path: Path = DATASET_PATH):
    with path.open(encoding="utf-8-sig", newline="") as handle: rows = list(csv.DictReader(handle))
    if not rows or not {"sample_id", "timestamp", "fire_label", *FULL_FEATURES}.issubset(rows[0]):
        raise LandcoverTerrainTrainingError("land-cover/terrain dataset schema is incompatible")
    assert_feature_allowlist(); output = []
    for row in rows:
        values = {field: float(row[field]) if row.get(field) not in {None, ""} else np.nan for field in FULL_FEATURES}
        output.append({**row, "_timestamp": parse_timestamp(row["timestamp"]), "_label": int(row["fire_label"]), "_environmental": values})
    return sorted(output, key=lambda row: (row["_timestamp"], row["sample_id"]))


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"); temporary.replace(path)


def _atomic_csv(path: Path, fields, rows) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def land_cover_audit(rows):
    grouped = {}
    for row in rows:
        category = row.get("land_cover_source_class") or "unavailable"
        counts = grouped.setdefault(category, Counter()); counts[int(row["_label"])] += 1
    return {category: {"rows": counts[0] + counts[1], "negative": counts[0], "positive": counts[1], "positive_rate": counts[1] / (counts[0] + counts[1])} for category, counts in sorted(grouped.items())}


def train(*, dataset_path=DATASET_PATH, output_directory=OUTPUT_DIRECTORY, seed=RANDOM_SEED, creation_time=None):
    rows = load_dataset(dataset_path); splits = temporal_split(rows); ablations = {}; fitted = {}
    for name, features in ABLATIONS.items():
        train_x, train_y = matrix_for(splits["train"], features); validation_x, validation_y = matrix_for(splits["validation"], features); test_x, test_y = matrix_for(splits["test"], features)
        selected_name, threshold, models, validation = fit_and_compare(train_x, train_y, validation_x, validation_y, seed=seed)
        probabilities = models[selected_name].predict_proba(test_x)[:, 1]
        ablations[name] = {"features": list(features), "selected_model": selected_name, "threshold": threshold, "validation_models": validation, "validation": validation[selected_name], "test": {"threshold_0_50": calculate_metrics(test_y, probabilities, .5), "selected_threshold": calculate_metrics(test_y, probabilities, threshold)}}
        fitted[name] = (models, probabilities, threshold)
    final_name = "current_plus_land_cover_and_slope"; models, probabilities, threshold = fitted[final_name]
    selected_name = ablations[final_name]["selected_model"]; selected = models[selected_name]
    validation_x, validation_y = matrix_for(splits["validation"], FULL_FEATURES)
    permutation = permutation_importance(selected, validation_x, validation_y, scoring="average_precision", n_repeats=5, random_state=seed, n_jobs=1)
    rankings = [{"model": selected_name, "importance_type": "validation_permutation_average_precision", "rank": rank, "feature": FULL_FEATURES[index], "value": float(permutation.importances_mean[index]), "absolute_value": abs(float(permutation.importances_mean[index])), "direction": ""} for rank, index in enumerate(np.argsort(permutation.importances_mean)[::-1], 1)]
    metadata = {"feature_names": list(FULL_FEATURES), "selected_model_type": selected_name, "threshold": threshold, "train_years": [2023, 2024], "validation_year": 2025, "test_year": 2026, "random_seed": seed, "sklearn_version": sklearn.__version__, "creation_timestamp": (creation_time or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"), "dataset_path": str(dataset_path)}
    metrics = {"metadata": metadata, "split_counts": split_counts(splits), "ablations": ablations, "full_validation_model_comparison": ablations[final_name]["validation_models"], "full_test": ablations[final_name]["test"], "test_geography_audit": geographic_audit(splits["test"], probabilities, threshold), "land_cover_class_audit_all_rows": land_cover_audit(rows), "land_cover_class_audit_test": land_cover_audit(splits["test"]), "selected_model_feature_importance": rankings}
    output_directory.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": selected, "metadata": metadata}, output_directory / MODEL_NAME)
    _atomic_json(output_directory / METRICS_NAME, metrics); _atomic_csv(output_directory / IMPORTANCE_NAME, tuple(rankings[0]), rankings)
    labels = (probabilities >= threshold).astype(int)
    predictions = [{"sample_id": row["sample_id"], "timestamp": row["timestamp"], "fire_label": row["_label"], "predicted_probability": float(probability), "predicted_label": int(label), "sample_type": row["sample_type"], "location_status": "mapped" if row.get("settlement_lamas_code") else "unlocated", "land_cover_source_class": row.get("land_cover_source_class"), "slope_degrees": row.get("slope_degrees")} for row, probability, label in zip(splits["test"], probabilities, labels)]
    _atomic_csv(output_directory / PREDICTIONS_NAME, tuple(predictions[0]), predictions); return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--dataset", type=Path, default=DATASET_PATH); parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY); args = parser.parse_args()
    metrics = train(dataset_path=args.dataset, output_directory=args.output_dir); print(json.dumps(metrics, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
