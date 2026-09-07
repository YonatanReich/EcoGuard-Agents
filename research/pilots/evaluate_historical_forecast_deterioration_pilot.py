"""Build and evaluate the completed 300-sample archived-forecast pilot offline."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from agents.fire_risk_prediction_agent import FireRiskPredictionAgent
from research.datasets.build_historical_environmental_features import PriorFirmsIndex, historical_fire_features
from research.datasets.build_historical_fire_negative_samples import load_firms_incidents
from research.datasets.build_historical_fire_weather_features import WeatherCheckpoint, checkpoint_configuration
from research.datasets.build_historical_forecast_ml_pilot_dataset import (
    CACHE_PATH, MANIFEST_PATH, MODEL_AVAILABILITY_DELAY_HOURS, SNAPSHOT_PLAN_PATH,
    ForecastRunCache, parse_utc, payload_contains_target,
)
from research.training.train_fire_prediction_landcover_terrain_models import DATASET_PATH as FEATURE_DATASET_PATH, FULL_FEATURES
from research.training.train_fire_prediction_models import RANDOM_SEED, calculate_metrics, select_threshold
from services.weather_feature_calculator import compute_features


OUTPUT_DATASET = Path("data/generated/fire_forecast_risk_pilot_dataset.csv")
OUTPUT_DIRECTORY = Path("data/generated/ml/forecast_risk_pilot")
METRICS_PATH = OUTPUT_DIRECTORY / "forecast_risk_pilot_metrics.json"
MODELS_PATH = OUTPUT_DIRECTORY / "forecast_risk_pilot_models.joblib"
PREDICTIONS_PATH = OUTPUT_DIRECTORY / "forecast_risk_pilot_test_predictions.csv"
FIRMS_PATH = Path("data/generated/firms_israel_candidate_incidents_2023_2026.csv")
POSITIVE_WEATHER = Path("data/generated/historical_fire_weather_checkpoint")
NEGATIVE_WEATHER = Path("data/generated/historical_fire_negative_weather_checkpoint")
HORIZONS = (12, 6, 3)

FORECAST_BASE_FIELDS = (
    "forecast_temperature_event", "forecast_humidity_event", "forecast_wind_speed_event",
    "forecast_wind_gust_event", "forecast_precipitation_event",
    "forecast_max_temperature_to_event", "forecast_min_humidity_to_event",
    "forecast_max_wind_speed_to_event", "forecast_max_wind_gust_to_event",
    "forecast_precipitation_sum_to_event", "forecast_temperature_change_c",
    "forecast_humidity_change_percentage_points", "forecast_wind_speed_change_kmh",
    "forecast_continued_no_precipitation",
)
BASELINE_FEATURES = tuple(f"current_risk_score_t{h}h" for h in HORIZONS)
FORECAST_FEATURES = tuple(f"{field}_t{h}h" for h in HORIZONS for field in FORECAST_BASE_FIELDS)
ENHANCED_FEATURES = BASELINE_FEATURES + FORECAST_FEATURES


class ForecastEvaluationError(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _weather_checkpoint(label: int) -> WeatherCheckpoint:
    path = POSITIVE_WEATHER if label else NEGATIVE_WEATHER
    return WeatherCheckpoint(path, checkpoint_configuration())


def _weather_candidate(sample: Mapping[str, Any]) -> dict[str, Any]:
    return {"candidate_id": sample["sample_id"], "start_timestamp": sample["timestamp"],
            "centroid_latitude": sample["latitude"], "centroid_longitude": sample["longitude"]}


def _current_features(sample: Mapping[str, Any], evaluation_time, weather: Mapping[str, Any],
                      firms_index: PriorFirmsIndex) -> dict[str, float]:
    weather_values, status = compute_features(weather, evaluation_time)
    if status != "success" or any(weather_values[name] is None for name in weather_values):
        raise ForecastEvaluationError(f"incomplete as-of weather features for {sample['sample_id']}")
    day = evaluation_time.timetuple().tm_yday
    values: dict[str, Any] = dict(weather_values)
    values.update({
        "sin_day_of_year": math.sin(2 * math.pi * day / 365.25),
        "cos_day_of_year": math.cos(2 * math.pi * day / 365.25),
        "sin_hour": math.sin(2 * math.pi * evaluation_time.hour / 24),
        "cos_hour": math.cos(2 * math.pi * evaluation_time.hour / 24),
    })
    values.update(historical_fire_features(
        firms_index, float(sample["latitude"]), float(sample["longitude"]), evaluation_time,
        excluded_candidate_ids=[sample["sample_id"]] if int(sample["fire_label"]) else (),
    ))
    for name in FULL_FEATURES:
        if name not in values:
            raw = sample.get(name)
            values[name] = float(raw) if raw not in {None, ""} else float("nan")
    return {name: float(values[name]) if values[name] is not None else float("nan") for name in FULL_FEATURES}


def forecast_features(payload: Mapping[str, Any], evaluation_time, target_time,
                      current: Mapping[str, Any]) -> dict[str, float]:
    """Tolerant equivalent of the qualitative forecast window semantics; missing stays NaN."""
    hourly = payload["hourly"]
    timestamps = [datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc) for value in hourly["time"]]
    indices = [index for index, timestamp in enumerate(timestamps) if evaluation_time < timestamp <= target_time]
    target_candidates = [index for index, timestamp in enumerate(timestamps) if timestamp <= target_time]
    if not indices or not target_candidates:
        raise ForecastEvaluationError("forecast has no evaluation-to-target window")
    target_index = min(target_candidates, key=lambda index: abs((timestamps[index] - target_time).total_seconds()))
    if timestamps[target_index] < target_time - timedelta(hours=1):
        raise ForecastEvaluationError("forecast does not cover target hour")
    def number(variable: str, index: int) -> float:
        try:
            value = float(hourly[variable][index])
            return value if math.isfinite(value) else float("nan")
        except (KeyError, IndexError, TypeError, ValueError):
            return float("nan")
    def values(variable: str) -> list[float]:
        return [value for value in (number(variable, index) for index in indices) if math.isfinite(value)]
    def aggregate(variable: str, operation) -> float:
        available = values(variable)
        return float(operation(available)) if available else float("nan")
    result = {
        "forecast_temperature_event": number("temperature_2m", target_index),
        "forecast_humidity_event": number("relative_humidity_2m", target_index),
        "forecast_wind_speed_event": number("wind_speed_10m", target_index),
        "forecast_wind_gust_event": number("wind_gusts_10m", target_index),
        "forecast_precipitation_event": number("precipitation", target_index),
        "forecast_max_temperature_to_event": aggregate("temperature_2m", max),
        "forecast_min_humidity_to_event": aggregate("relative_humidity_2m", min),
        "forecast_max_wind_speed_to_event": aggregate("wind_speed_10m", max),
        "forecast_max_wind_gust_to_event": aggregate("wind_gusts_10m", max),
        "forecast_precipitation_sum_to_event": aggregate("precipitation", sum),
    }
    def delta(forecast_name: str, current_name: str) -> float:
        left, right = result[forecast_name], float(current[current_name])
        return left - right if math.isfinite(left) and math.isfinite(right) else float("nan")
    result.update({
        "forecast_temperature_change_c": delta("forecast_temperature_event", "temperature_1h_before"),
        "forecast_humidity_change_percentage_points": delta("forecast_humidity_event", "humidity_1h_before"),
        "forecast_wind_speed_change_kmh": delta("forecast_wind_speed_event", "wind_speed_1h_before"),
    })
    precipitation = result["forecast_precipitation_sum_to_event"]
    current_precipitation = float(current["precipitation_1h_before"])
    result["forecast_continued_no_precipitation"] = (
        float(precipitation == 0 and current_precipitation == 0)
        if math.isfinite(precipitation) and math.isfinite(current_precipitation) else float("nan")
    )
    return result


def build_evaluation_rows(
    manifest: Sequence[Mapping[str, Any]], snapshots: Sequence[Mapping[str, Any]],
    feature_rows: Sequence[Mapping[str, Any]], cache: ForecastRunCache,
    predictor: FireRiskPredictionAgent, firms_index: PriorFirmsIndex,
) -> list[dict[str, Any]]:
    by_feature = {row["sample_id"]: row for row in feature_rows}
    by_snapshot = {(row["sample_id"], int(row["horizon_hours"])): row for row in snapshots}
    positive_checkpoint, negative_checkpoint = _weather_checkpoint(1), _weather_checkpoint(0)
    output = []
    for item in manifest:
        sample = {**by_feature[item["sample_id"]], **item}
        label = int(sample["fire_label"])
        weather = (positive_checkpoint if label else negative_checkpoint).load(_weather_candidate(sample))
        if weather is None:
            raise ForecastEvaluationError(f"missing historical weather checkpoint for {sample['sample_id']}")
        row: dict[str, Any] = {"sample_id": sample["sample_id"], "timestamp": sample["timestamp"],
                               "year": int(item["year"]), "fire_label": label, "sample_type": sample["sample_type"]}
        for horizon in HORIZONS:
            snapshot = by_snapshot[(sample["sample_id"], horizon)]
            evaluation = parse_utc(snapshot["evaluation_time"])
            current_values = _current_features(sample, evaluation, weather, firms_index)
            prediction = predictor.predict(current_values)
            if prediction["status"] != "ok":
                raise ForecastEvaluationError(f"Current Risk failed for {sample['sample_id']} T-{horizon}h")
            actual_run = cache.resolved_run(snapshot)
            if actual_run is None:
                raise ForecastEvaluationError(f"forecast snapshot unresolved for {sample['sample_id']} T-{horizon}h")
            if actual_run + timedelta(hours=MODEL_AVAILABILITY_DELAY_HOURS) > evaluation:
                raise ForecastEvaluationError("forecast run violates conservative availability")
            payload = cache.load(float(sample["latitude"]), float(sample["longitude"]), actual_run)
            if payload is None or not payload_contains_target(payload, snapshot):
                raise ForecastEvaluationError("resolved forecast payload is missing its target hour")
            forecast = forecast_features(payload, evaluation, parse_utc(snapshot["forecast_target_time"]), current_values)
            row[f"current_risk_score_t{horizon}h"] = prediction["risk_score"]
            row[f"actual_run_initialization_t{horizon}h"] = actual_run.isoformat().replace("+00:00", "Z")
            row[f"evaluation_time_t{horizon}h"] = snapshot["evaluation_time"]
            for field in FORECAST_BASE_FIELDS:
                row[f"{field}_t{horizon}h"] = forecast[field]
        output.append(row)
    return sorted(output, key=lambda row: (row["timestamp"], row["sample_id"]))


def temporal_split(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    result = {"train": [], "validation": [], "test": []}
    names = {2024: "train", 2025: "validation", 2026: "test"}
    for row in rows:
        result[names[int(row["year"])]].append(row)
    if any(len(values) != 100 for values in result.values()):
        raise ForecastEvaluationError("pilot temporal split must contain exactly 100 samples per year")
    return result


def _matrix(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray([[float(row[name]) for name in fields] for row in rows]), np.asarray([int(row["fire_label"]) for row in rows])


def _model() -> Pipeline:
    return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()),
                     ("model", LogisticRegression(class_weight="balanced", max_iter=1000, random_state=RANDOM_SEED))])


def evaluate(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Pipeline], list[dict[str, Any]]]:
    splits = temporal_split(rows); metrics: dict[str, Any] = {}; models = {}; predictions = []
    for name, fields in (("current_risk_only", BASELINE_FEATURES), ("current_risk_plus_forecast", ENHANCED_FEATURES)):
        train_x, train_y = _matrix(splits["train"], fields)
        validation_x, validation_y = _matrix(splits["validation"], fields)
        test_x, test_y = _matrix(splits["test"], fields)
        model = _model(); model.fit(train_x, train_y)
        validation_probability = model.predict_proba(validation_x)[:, 1]
        threshold, validation_metrics = select_threshold(validation_y, validation_probability)
        test_probability = model.predict_proba(test_x)[:, 1]
        test_metrics = calculate_metrics(test_y, test_probability, threshold)
        metrics[name] = {"features": list(fields), "threshold_selected_on_2025": threshold,
                         "validation_2025": validation_metrics, "test_2026": test_metrics}
        models[name] = model
        for row, probability in zip(splits["test"], test_probability):
            predictions.append({"sample_id": row["sample_id"], "timestamp": row["timestamp"],
                                "fire_label": row["fire_label"], "model": name,
                                "probability": float(probability), "threshold": threshold,
                                "predicted_label": int(probability >= threshold)})
    baseline, enhanced = metrics["current_risk_only"], metrics["current_risk_plus_forecast"]
    metrics["deltas_enhanced_minus_baseline"] = {
        split: {field: enhanced[split][field] - baseline[split][field]
                for field in ("roc_auc", "pr_auc", "accuracy", "precision", "recall", "f1", "brier_score")}
        for split in ("validation_2025", "test_2026")
    }
    metrics["split_counts"] = {name: {"rows": len(values), "positive": sum(int(r["fire_label"]) for r in values),
                                              "negative": sum(not int(r["fire_label"]) for r in values)}
                               for name, values in splits.items()}
    metrics["forecast_feature_missing_counts"] = {
        name: sum(not math.isfinite(float(row[name])) for row in rows) for name in FORECAST_FEATURES
    }
    return metrics, models, predictions


def _atomic_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def run() -> dict[str, Any]:
    manifest, snapshots, features = _read_csv(MANIFEST_PATH), _read_csv(SNAPSHOT_PLAN_PATH), _read_csv(FEATURE_DATASET_PATH)
    cache = ForecastRunCache(CACHE_PATH); cache.initialize()
    rows = build_evaluation_rows(manifest, snapshots, features, cache, FireRiskPredictionAgent(),
                                 PriorFirmsIndex(load_firms_incidents(FIRMS_PATH)))
    metrics, models, predictions = evaluate(rows)
    _atomic_csv(OUTPUT_DATASET, rows); _atomic_csv(PREDICTIONS_PATH, predictions)
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = METRICS_PATH.with_suffix(".tmp"); temporary.write_text(json.dumps(metrics, indent=2), encoding="utf-8"); temporary.replace(METRICS_PATH)
    joblib.dump({"models": models, "baseline_features": BASELINE_FEATURES, "enhanced_features": ENHANCED_FEATURES,
                 "random_seed": RANDOM_SEED, "semantics": "experimental_historical_forecast_pilot"}, MODELS_PATH)
    return metrics


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        print(json.dumps(run(), indent=2))
    except (ForecastEvaluationError, OSError, ValueError, KeyError) as error:
        print(f"Forecast evaluation failed: {error}"); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
