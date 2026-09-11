"""Train temporal baseline models using only pre-event weather features."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from research.datasets.build_historical_fire_weather_features import FEATURE_FIELDS


DATASET_PATH = Path("data/generated/fire_prediction_ml_dataset_2023_2026.csv")
OUTPUT_DIRECTORY = Path("data/generated/ml")
MODEL_PATH = OUTPUT_DIRECTORY / "fire_prediction_model.joblib"
METRICS_PATH = OUTPUT_DIRECTORY / "fire_prediction_metrics.json"
IMPORTANCE_PATH = OUTPUT_DIRECTORY / "fire_prediction_feature_importance.csv"
PREDICTIONS_PATH = OUTPUT_DIRECTORY / "fire_prediction_test_predictions.csv"

RANDOM_SEED = 20260827
TRAIN_YEARS = (2023, 2024)
VALIDATION_YEAR = 2025
TEST_YEAR = 2026
ML_FEATURES = tuple(FEATURE_FIELDS)

FORBIDDEN_FEATURES = frozenset(
    {
        "sample_id", "sample_type", "timestamp", "latitude", "longitude",
        "settlement", "settlement_lamas_code", "fire_label", "label_source",
        "official_month_support", "official_event_count",
        "firms_candidates_same_settlement_month", "ground_truth_status",
        "reference_positive_candidate_id", "sample_generation_method",
        "weather_source", "weather_collection_status", "weather_error",
        "max_frp", "mean_frp", "hotspot_count", "firms_confidence",
        "confidence", "satellite", "satellites", "instrument",
        "source_product", "source_products",
    }
)


class TrainingError(RuntimeError):
    """Dataset, leakage, split, or artifact validation failure."""


def parse_timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise TrainingError("dataset contains a malformed timestamp") from None
    if parsed.tzinfo is None:
        raise TrainingError("dataset timestamp has no UTC offset")
    return parsed.astimezone(timezone.utc)


def assert_feature_allowlist(features: Iterable[str]) -> tuple[str, ...]:
    selected = tuple(features)
    if selected != ML_FEATURES:
        raise TrainingError("ML feature order differs from the historical weather allowlist")
    leaked = set(selected) & FORBIDDEN_FEATURES
    if leaked:
        raise TrainingError(f"forbidden leakage fields selected: {sorted(leaked)}")
    return selected


def load_dataset(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        raise TrainingError(f"ML dataset is missing: {path}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        raise TrainingError("ML dataset is malformed") from None
    required = {
        "sample_id", "sample_type", "timestamp", "latitude", "longitude",
        "settlement_lamas_code", "fire_label", *ML_FEATURES,
    }
    if not rows or not required.issubset(rows[0]):
        raise TrainingError("ML dataset has an incompatible schema")
    assert_feature_allowlist(ML_FEATURES)
    normalized = []
    for row in rows:
        try:
            label = int(row["fire_label"])
            values = [float(row[field]) for field in ML_FEATURES]
        except (TypeError, ValueError):
            raise TrainingError("ML dataset contains missing or nonnumeric features") from None
        if label not in {0, 1} or any(not math.isfinite(value) for value in values):
            raise TrainingError("ML dataset contains invalid labels or feature values")
        normalized.append({**row, "_timestamp": parse_timestamp(row["timestamp"]), "_label": label, "_features": values})
    identifiers = [row["sample_id"] for row in normalized]
    if len(identifiers) != len(set(identifiers)):
        raise TrainingError("ML dataset contains duplicate sample IDs")
    return sorted(normalized, key=lambda row: (row["_timestamp"], row["sample_id"]))


def temporal_split(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    splits = {"train": [], "validation": [], "test": []}
    for row in rows:
        year = row["_timestamp"].year
        if year in TRAIN_YEARS:
            splits["train"].append(row)
        elif year == VALIDATION_YEAR:
            splits["validation"].append(row)
        elif year == TEST_YEAR:
            splits["test"].append(row)
        else:
            raise TrainingError(f"dataset year is outside configured split: {year}")
    if any(not split for split in splits.values()):
        raise TrainingError("one or more temporal splits are empty")
    if not (
        max(row["_timestamp"] for row in splits["train"])
        < min(row["_timestamp"] for row in splits["validation"])
        and max(row["_timestamp"] for row in splits["validation"])
        < min(row["_timestamp"] for row in splits["test"])
    ):
        raise TrainingError("temporal split ordering is invalid")
    return splits


def matrix(rows: list[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.asarray([row["_features"] for row in rows], dtype=float),
        np.asarray([row["_label"] for row in rows], dtype=int),
    )


def build_models(seed: int = RANDOM_SEED) -> dict[str, Pipeline]:
    imputer = lambda: SimpleImputer(strategy="median")
    return {
        "dummy": Pipeline([("imputer", imputer()), ("model", DummyClassifier(strategy="prior"))]),
        "logistic_regression": Pipeline(
            [
                ("imputer", imputer()),
                ("scaler", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        class_weight="balanced", max_iter=1000, random_state=seed
                    ),
                ),
            ]
        ),
        "random_forest": Pipeline(
            [
                ("imputer", imputer()),
                (
                    "model",
                    RandomForestClassifier(
                        n_estimators=150,
                        max_depth=12,
                        min_samples_leaf=5,
                        class_weight="balanced_subsample",
                        random_state=seed,
                        n_jobs=1,
                    ),
                ),
            ]
        ),
        "hist_gradient_boosting": Pipeline(
            [
                ("imputer", imputer()),
                (
                    "model",
                    HistGradientBoostingClassifier(
                        learning_rate=0.05,
                        max_iter=100,
                        max_leaf_nodes=15,
                        min_samples_leaf=20,
                        l2_regularization=0.1,
                        class_weight="balanced",
                        random_state=seed,
                    ),
                ),
            ]
        ),
    }


def calculate_metrics(labels: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict[str, Any]:
    predictions = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    unique = np.unique(labels)
    return {
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(labels, predictions)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(labels, probabilities)) if len(unique) == 2 else None,
        "pr_auc": float(average_precision_score(labels, probabilities)) if len(unique) == 2 else None,
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "predicted_positive_rate": float(predictions.mean()),
        "positive_prevalence": float(labels.mean()),
    }


def select_threshold(labels: np.ndarray, probabilities: np.ndarray) -> tuple[float, dict[str, Any]]:
    """Select on validation only: maximize F1, then precision+recall balance."""
    candidates = []
    for threshold in np.linspace(0.10, 0.90, 161):
        metrics = calculate_metrics(labels, probabilities, float(threshold))
        balance = -abs(metrics["precision"] - metrics["recall"])
        candidates.append((metrics["f1"], balance, -abs(float(threshold) - 0.5), float(threshold), metrics))
    best = max(candidates, key=lambda item: item[:4])
    return best[3], best[4]


def fit_and_compare(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    *,
    seed: int = RANDOM_SEED,
) -> tuple[str, float, dict[str, Pipeline], dict[str, Any]]:
    models = build_models(seed)
    comparison = {}
    for name, pipeline in models.items():
        pipeline.fit(train_x, train_y)
        probabilities = pipeline.predict_proba(validation_x)[:, 1]
        threshold, selected_metrics = select_threshold(validation_y, probabilities)
        comparison[name] = {
            "threshold_0_50": calculate_metrics(validation_y, probabilities, 0.5),
            "selected_threshold": threshold,
            "selected_threshold_metrics": selected_metrics,
        }
    # Model choice is validation-only: PR-AUC first, then selected-threshold F1
    # and recall. The dummy remains reported but cannot win ties over a real model.
    selected_name = max(
        comparison,
        key=lambda name: (
            comparison[name]["selected_threshold_metrics"]["pr_auc"],
            comparison[name]["selected_threshold_metrics"]["f1"],
            comparison[name]["selected_threshold_metrics"]["recall"],
            name != "dummy",
        ),
    )
    return (
        selected_name,
        comparison[selected_name]["selected_threshold"],
        models,
        comparison,
    )


def split_counts(splits: Mapping[str, list[Mapping[str, Any]]]) -> dict[str, Any]:
    result = {}
    for name, rows in splits.items():
        counts = Counter(int(row["_label"]) for row in rows)
        result[name] = {"rows": len(rows), "negative": counts[0], "positive": counts[1]}
    return result


def geographic_audit(
    rows: list[Mapping[str, Any]], probabilities: np.ndarray, threshold: float
) -> dict[str, Any]:
    result = {}
    for status, mapped in (("mapped", True), ("unlocated", False)):
        indices = [
            index
            for index, row in enumerate(rows)
            if bool(str(row.get("settlement_lamas_code", "")).strip()) == mapped
        ]
        if not indices:
            result[status] = {"rows": 0, "metrics": None}
            continue
        labels = np.asarray([rows[index]["_label"] for index in indices], dtype=int)
        subset_probabilities = probabilities[indices]
        result[status] = {
            "rows": len(indices),
            "positive": int(labels.sum()),
            "negative": int(len(labels) - labels.sum()),
            "metrics": calculate_metrics(labels, subset_probabilities, threshold),
        }
    return result


def feature_rankings(
    models: Mapping[str, Pipeline], feature_names: tuple[str, ...] = ML_FEATURES
) -> list[dict[str, Any]]:
    rows = []
    logistic = models["logistic_regression"].named_steps["model"]
    coefficients = logistic.coef_[0]
    for rank, index in enumerate(np.argsort(np.abs(coefficients))[::-1], start=1):
        value = float(coefficients[index])
        rows.append(
            {
                "model": "logistic_regression",
                "importance_type": "standardized_coefficient",
                "rank": rank,
                "feature": feature_names[index],
                "value": value,
                "absolute_value": abs(value),
                "direction": "positive" if value >= 0 else "negative",
            }
        )
    forest = models["random_forest"].named_steps["model"]
    importances = forest.feature_importances_
    for rank, index in enumerate(np.argsort(importances)[::-1], start=1):
        value = float(importances[index])
        rows.append(
            {
                "model": "random_forest",
                "importance_type": "impurity_importance",
                "rank": rank,
                "feature": feature_names[index],
                "value": value,
                "absolute_value": value,
                "direction": "",
            }
        )
    return rows


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_csv(path: Path, fields: tuple[str, ...], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def train_and_evaluate(
    *,
    dataset_path: Path = DATASET_PATH,
    output_directory: Path = OUTPUT_DIRECTORY,
    seed: int = RANDOM_SEED,
    creation_time: datetime | None = None,
) -> dict[str, Any]:
    rows = load_dataset(dataset_path)
    splits = temporal_split(rows)
    train_x, train_y = matrix(splits["train"])
    validation_x, validation_y = matrix(splits["validation"])
    test_x, test_y = matrix(splits["test"])
    selected_name, threshold, models, validation = fit_and_compare(
        train_x, train_y, validation_x, validation_y, seed=seed
    )
    selected = models[selected_name]
    test_probabilities = selected.predict_proba(test_x)[:, 1]
    test_metrics = {
        "threshold_0_50": calculate_metrics(test_y, test_probabilities, 0.5),
        "selected_threshold": calculate_metrics(test_y, test_probabilities, threshold),
    }
    metadata = {
        "feature_names": list(ML_FEATURES),
        "selected_model_type": selected_name,
        "threshold": threshold,
        "train_years": list(TRAIN_YEARS),
        "validation_year": VALIDATION_YEAR,
        "test_year": TEST_YEAR,
        "random_seed": seed,
        "sklearn_version": sklearn.__version__,
        "creation_timestamp": (creation_time or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
        "dataset_path": str(dataset_path),
    }
    metrics = {
        "metadata": metadata,
        "split_counts": split_counts(splits),
        "temporal_boundaries": {
            "max_train": max(row["_timestamp"] for row in splits["train"]).isoformat(),
            "min_validation": min(row["_timestamp"] for row in splits["validation"]).isoformat(),
            "max_validation": max(row["_timestamp"] for row in splits["validation"]).isoformat(),
            "min_test": min(row["_timestamp"] for row in splits["test"]).isoformat(),
        },
        "validation_model_comparison": validation,
        "selected_model": selected_name,
        "selected_threshold": threshold,
        "test_metrics": test_metrics,
        "test_geography_audit": geographic_audit(splits["test"], test_probabilities, threshold),
        "limitations": [
            "2026 is a partial-year test split with relatively few positives.",
            "Positive labels combine FIRMS candidates with monthly aggregate support; they are not individual confirmations.",
            "Negative labels are FIRMS non-observation proxies, not proof that no fire existed.",
            "The positive set has no unlocated samples, so open-area positive performance cannot be validated.",
            "Feature importance and coefficients are associations, not causal effects.",
        ],
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    model_path = output_directory / MODEL_PATH.name
    temporary_model = model_path.with_suffix(model_path.suffix + ".tmp")
    try:
        joblib.dump({"pipeline": selected, "metadata": metadata}, temporary_model)
        temporary_model.replace(model_path)
    finally:
        if temporary_model.exists():
            temporary_model.unlink()
    _atomic_json(output_directory / METRICS_PATH.name, metrics)
    _atomic_csv(
        output_directory / IMPORTANCE_PATH.name,
        ("model", "importance_type", "rank", "feature", "value", "absolute_value", "direction"),
        feature_rankings(models),
    )
    predictions = []
    predicted_labels = (test_probabilities >= threshold).astype(int)
    for row, probability, prediction in zip(splits["test"], test_probabilities, predicted_labels):
        predictions.append(
            {
                "sample_id": row["sample_id"],
                "timestamp": row["timestamp"],
                "fire_label": row["_label"],
                "predicted_probability": float(probability),
                "predicted_label": int(prediction),
                "sample_type": row["sample_type"],
                "location_status": "mapped" if row.get("settlement_lamas_code") else "unlocated",
            }
        )
    _atomic_csv(
        output_directory / PREDICTIONS_PATH.name,
        ("sample_id", "timestamp", "fire_label", "predicted_probability", "predicted_label", "sample_type", "location_status"),
        predictions,
    )
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    args = parser.parse_args()
    try:
        metrics = train_and_evaluate(
            dataset_path=args.dataset, output_directory=args.output_dir, seed=args.seed
        )
    except TrainingError as error:
        print(f"Baseline training failed: {error}")
        return 1
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
