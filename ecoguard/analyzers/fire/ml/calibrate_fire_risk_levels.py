"""Turning model scores into risk levels that mean something.

A model can rank well and still be badly calibrated - saying 80% when it is
right half the time. This fits the correction, then sets the boundaries between
low, medium and high, and reports what actually happened in each band so the
bands can be argued with."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
import sklearn
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from ecoguard.analyzers.fire.ml.train_fire_prediction_landcover_terrain_models import (
    DATASET_PATH,
    IMPORTANCE_NAME,
    MODEL_NAME,
    OUTPUT_DIRECTORY,
    load_dataset,
    matrix_for,
    temporal_split,
)
from ecoguard.paths import GENERATED

OUTPUT_PATH = GENERATED / "ml" / "fire_risk_thresholds.json"
MODEL_PATH = OUTPUT_DIRECTORY / MODEL_NAME
FEATURE_IMPORTANCE_PATH = OUTPUT_DIRECTORY / IMPORTANCE_NAME
RANDOM_SEED = 42
CALIBRATION_FOLDS = 5
HIGH_MAX_ALERT_RATE = 0.30
MEDIUM_HIGH_MIN_RECALL = 0.90


class CalibrationError(RuntimeError):
    """Raised when calibration inputs or artifacts are incompatible."""


def _logit(probabilities: np.ndarray) -> np.ndarray:
    """Probabilities on the scale the calibration is fitted in."""
    clipped = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def expected_calibration_error(labels: Sequence[int], scores: Sequence[float], bins: int = 10) -> float:
    """How far the model's stated confidence is from how often it is right."""
    y = np.asarray(labels, dtype=int)
    p = np.asarray(scores, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    result = 0.0
    for index in range(bins):
        mask = (p >= edges[index]) & (p < edges[index + 1] if index < bins - 1 else p <= edges[index + 1])
        if np.any(mask):
            result += float(np.mean(mask)) * abs(float(np.mean(y[mask])) - float(np.mean(p[mask])))
    return result


def calibration_metrics(labels: Sequence[int], scores: Sequence[float]) -> dict[str, float]:
    """How well the model's confidence matches reality."""
    y = np.asarray(labels, dtype=int)
    p = np.asarray(scores, dtype=float)
    return {
        "brier_score": float(brier_score_loss(y, p)),
        "expected_calibration_error_10_bins": expected_calibration_error(y, p),
        "roc_auc": float(roc_auc_score(y, p)),
        "average_precision": float(average_precision_score(y, p)),
    }


def compare_calibration_methods(raw_scores: Sequence[float], labels: Sequence[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compare calibration methods using out-of-fold 2025 predictions only."""
    raw = np.asarray(raw_scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    folds = StratifiedKFold(n_splits=CALIBRATION_FOLDS, shuffle=True, random_state=RANDOM_SEED)
    sigmoid = LogisticRegression(random_state=RANDOM_SEED)
    isotonic = IsotonicRegression(out_of_bounds="clip")
    sigmoid_oof = cross_val_predict(sigmoid, _logit(raw), y, cv=folds, method="predict_proba")[:, 1]
    isotonic_oof = cross_val_predict(isotonic, raw, y, cv=folds, method="predict")
    candidates = {"raw": raw, "sigmoid": sigmoid_oof, "isotonic": isotonic_oof}
    comparison = {name: calibration_metrics(y, scores) for name, scores in candidates.items()}
    # Calibration should improve reliability without materially destroying the
    # base model's validation ranking. Isotonic mappings can introduce many
    # ties, so exclude methods losing more than 0.01 AP or ROC-AUC versus raw.
    eligible = [
        name
        for name in candidates
        if comparison[name]["average_precision"] >= comparison["raw"]["average_precision"] - 0.01
        and comparison[name]["roc_auc"] >= comparison["raw"]["roc_auc"] - 0.01
    ]
    selected = min(eligible, key=lambda name: (comparison[name]["brier_score"], comparison[name]["expected_calibration_error_10_bins"]))
    if selected == "sigmoid":
        fitted = sigmoid.fit(_logit(raw), y)
        parameters = {"coefficient": float(fitted.coef_[0, 0]), "intercept": float(fitted.intercept_[0])}
    elif selected == "isotonic":
        fitted = isotonic.fit(raw, y)
        parameters = {
            "x_thresholds": [float(value) for value in fitted.X_thresholds_],
            "y_thresholds": [float(value) for value in fitted.y_thresholds_],
        }
    else:
        parameters = {}
    return {
        "selected_method": selected,
        "comparison": comparison,
        "out_of_fold_scores": [float(value) for value in candidates[selected]],
    }, parameters


def apply_calibration(raw_scores: Sequence[float], method: str, parameters: Mapping[str, Any]) -> np.ndarray:
    """Adjust raw scores so a stated confidence means what it says."""
    raw = np.asarray(raw_scores, dtype=float)
    if method == "raw":
        return np.clip(raw, 0.0, 1.0)
    if method == "sigmoid":
        linear = float(parameters["coefficient"]) * _logit(raw).ravel() + float(parameters["intercept"])
        return 1.0 / (1.0 + np.exp(-np.clip(linear, -709, 709)))
    if method == "isotonic":
        return np.interp(raw, parameters["x_thresholds"], parameters["y_thresholds"])
    raise CalibrationError(f"unsupported calibration method: {method}")


def derive_risk_thresholds(scores: Sequence[float], labels: Sequence[int]) -> tuple[float, float, dict[str, Any]]:
    """Derive alert-bounded HIGH and high-recall MEDIUM+ thresholds."""
    p = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    high_options: list[tuple[float, float, float, float, float]] = []
    for threshold in np.unique(p):
        predicted = p >= threshold
        if not np.any(predicted) or float(np.mean(predicted)) > HIGH_MAX_ALERT_RATE:
            continue
        tp = int(np.sum(predicted & (y == 1)))
        fp = int(np.sum(predicted & (y == 0)))
        fn = int(np.sum(~predicted & (y == 1)))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        high_options.append((f1, precision, recall, float(threshold), float(np.mean(predicted))))
    if not high_options:
        raise CalibrationError("no valid HIGH threshold candidate")
    high = max(high_options, key=lambda item: (item[0], item[1], item[2], item[3]))

    low_options: list[tuple[float, float]] = []
    positives = int(np.sum(y == 1))
    for threshold in np.unique(p[p < high[3]]):
        monitored = p >= threshold
        recall = float(np.sum(monitored & (y == 1)) / positives) if positives else 0.0
        if recall >= MEDIUM_HIGH_MIN_RECALL:
            low_options.append((float(threshold), recall))
    if not low_options:
        raise CalibrationError("no valid LOW/MEDIUM threshold candidate")
    low = max(low_options, key=lambda item: item[0])
    return low[0], high[3], {
        "rule": (
            "HIGH maximizes validation F1 subject to at most 30% HIGH alert burden; "
            "MEDIUM+ uses the highest boundary retaining at least 90% validation-positive recall."
        ),
        "high_validation_f1": high[0],
        "high_validation_precision": high[1],
        "high_validation_recall": high[2],
        "high_validation_alert_rate": high[4],
        "medium_or_high_validation_recall": low[1],
    }


def assign_risk_levels(scores: Sequence[float], low_medium: float, medium_high: float) -> np.ndarray:
    """Turn calibrated scores into low, medium and high."""
    p = np.asarray(scores, dtype=float)
    return np.where(p >= medium_high, "high", np.where(p >= low_medium, "medium", "low"))


def bucket_statistics(labels: Sequence[int], scores: Sequence[float], low_medium: float, medium_high: float) -> dict[str, Any]:
    """What actually happened in each risk level, so the bands can be checked."""
    y = np.asarray(labels, dtype=int)
    p = np.asarray(scores, dtype=float)
    levels = assign_risk_levels(p, low_medium, medium_high)
    total_positives = int(np.sum(y == 1))
    result: dict[str, Any] = {}
    for level in ("low", "medium", "high"):
        mask = levels == level
        count = int(np.sum(mask))
        positives = int(np.sum(y[mask] == 1))
        result[level] = {
            "row_count": count,
            "positive_count": positives,
            "positive_prevalence": positives / count if count else None,
            "fraction_of_all_positives": positives / total_positives if total_positives else None,
            "average_score": float(np.mean(p[mask])) if count else None,
            "minimum_score": float(np.min(p[mask])) if count else None,
            "maximum_score": float(np.max(p[mask])) if count else None,
        }
    prevalences = [result[level]["positive_prevalence"] for level in ("low", "medium", "high")]
    result["monotonic_positive_prevalence"] = bool(all(a <= b for a, b in zip(prevalences, prevalences[1:])))
    return result


def _feature_references(rows: Sequence[Mapping[str, Any]], features: Sequence[str]) -> dict[str, dict[str, float]]:
    """The inputs each record carried, for the report."""
    matrix, _ = matrix_for(rows, features)
    return {
        feature: {
            "median": float(np.nanmedian(matrix[:, index])),
            "q25": float(np.nanquantile(matrix[:, index], 0.25)),
            "q75": float(np.nanquantile(matrix[:, index], 0.75)),
        }
        for index, feature in enumerate(features)
    }


def _global_importance(path: Path) -> list[dict[str, Any]]:
    """Which inputs the trained model leaned on most."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [{"feature": row["feature"], "rank": int(row["rank"]), "importance": float(row["value"])} for row in rows]


def build_calibration(model_path: Path = MODEL_PATH, dataset_path: Path = DATASET_PATH, output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    """Fit the calibration and the risk bands, and write them out."""
    bundle = joblib.load(model_path)
    pipeline = bundle["pipeline"]
    feature_names = list(bundle["metadata"]["feature_names"])
    splits = temporal_split(load_dataset(dataset_path))
    validation_x, validation_y = matrix_for(splits["validation"], feature_names)
    test_x, test_y = matrix_for(splits["test"], feature_names)
    validation_raw = pipeline.predict_proba(validation_x)[:, 1]
    test_raw = pipeline.predict_proba(test_x)[:, 1]
    comparison, parameters = compare_calibration_methods(validation_raw, validation_y)
    method = comparison["selected_method"]
    validation_oof = np.asarray(comparison.pop("out_of_fold_scores"), dtype=float)
    test_scores = apply_calibration(test_raw, method, parameters)
    low_medium, medium_high, threshold_details = derive_risk_thresholds(validation_oof, validation_y)
    payload = {
        "schema_version": 1,
        "risk_semantics": "estimated_fire_risk",
        "semantics_note": "Scores indicate similarity to historically higher-risk fire conditions; they are not a guarantee or detection of an actual fire.",
        "model_path": model_path.as_posix(),
        "model_version": f"landcover-terrain-{datetime.now(timezone.utc).date().isoformat()}",
        "model_type": bundle["metadata"]["selected_model_type"],
        "model_sklearn_version": bundle["metadata"].get("sklearn_version", sklearn.__version__),
        "feature_count": len(feature_names),
        "feature_names": feature_names,
        "calibration": {
            "method": method,
            "fit_year": 2025,
            "selection": "lowest 5-fold out-of-fold 2025 Brier score among methods within 0.01 of raw AP and ROC-AUC; ECE breaks ties",
            "parameters": parameters,
            "comparison_validation_oof": comparison["comparison"],
            "test_metrics_untouched_2026": calibration_metrics(test_y, test_scores),
        },
        "low_medium_threshold": low_medium,
        "medium_high_threshold": medium_high,
        "threshold_selection": threshold_details,
        "validation_year": 2025,
        "test_year": 2026,
        "validation_bucket_statistics_oof": bucket_statistics(validation_y, validation_oof, low_medium, medium_high),
        "test_bucket_statistics_untouched_2026": bucket_statistics(test_y, test_scores, low_medium, medium_high),
        "feature_reference_train_2023_2024": _feature_references(splits["train"], feature_names),
        "global_feature_importance": _global_importance(FEATURE_IMPORTANCE_PATH),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": dataset_path.as_posix(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return payload


def main() -> None:
    """Run the calibration from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    result = build_calibration(args.model, args.dataset, args.output)
    print(f"Calibration: {result['calibration']['method']}")
    print(f"LOW/MEDIUM threshold: {result['low_medium_threshold']:.6f}")
    print(f"MEDIUM/HIGH threshold: {result['medium_high_threshold']:.6f}")
    for split_key in ("validation_bucket_statistics_oof", "test_bucket_statistics_untouched_2026"):
        print(split_key)
        print(json.dumps(result[split_key], indent=2))


if __name__ == "__main__":
    main()
