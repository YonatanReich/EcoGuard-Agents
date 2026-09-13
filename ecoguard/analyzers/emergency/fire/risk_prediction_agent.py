"""Standalone inference interface for estimated fire-risk conditions."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np

from ecoguard.research.training.calibrate_fire_risk_levels import apply_calibration
from ecoguard.paths import GENERATED

DEFAULT_MODEL_PATH = GENERATED / "ml" / "fire_prediction_landcover_terrain_model.joblib"
DEFAULT_THRESHOLDS_PATH = GENERATED / "ml" / "fire_risk_thresholds.json"


class FireRiskPredictionAgent:
    """Score a complete, pre-collected 44-feature payload without acquiring data."""

    def __init__(self, model_path: Path | str = DEFAULT_MODEL_PATH, thresholds_path: Path | str = DEFAULT_THRESHOLDS_PATH):
        self.model_path = Path(model_path)
        self.thresholds_path = Path(thresholds_path)
        self._pipeline = None
        self._metadata: dict[str, Any] | None = None

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        bundle = joblib.load(self.model_path)
        metadata = json.loads(self.thresholds_path.read_text(encoding="utf-8"))
        model_features = list(bundle.get("metadata", {}).get("feature_names", []))
        threshold_features = list(metadata.get("feature_names", []))
        if not model_features or model_features != threshold_features:
            raise ValueError("model and fire-risk metadata feature schemas are incompatible")
        if len(model_features) != int(metadata.get("feature_count", -1)):
            raise ValueError("fire-risk metadata feature count is incompatible")
        low = float(metadata["low_medium_threshold"])
        high = float(metadata["medium_high_threshold"])
        if not 0.0 <= low < high <= 1.0:
            raise ValueError("fire-risk thresholds are invalid")
        self._pipeline = bundle["pipeline"]
        self._metadata = metadata

    @property
    def feature_names(self) -> tuple[str, ...]:
        self._load()
        return tuple(self._metadata["feature_names"])

    @property
    def calibration_metadata(self) -> Mapping[str, Any]:
        self._load()
        return self._metadata

    def predict(self, features: Mapping[str, Any]) -> dict[str, Any]:
        try:
            self._load()
            if not isinstance(features, Mapping):
                return self._error("invalid_payload", "features must be a mapping")
            required = list(self._metadata["feature_names"])
            missing = [name for name in required if name not in features]
            unexpected = sorted(set(features) - set(required))
            if missing:
                return self._error("missing_features", "required features are missing", {"features": missing})
            if unexpected:
                return self._error("unexpected_features", "payload contains unknown features", {"features": unexpected})
            values: list[float] = []
            for name in required:
                value = features[name]
                if value is None or isinstance(value, bool):
                    return self._error("invalid_feature_value", f"{name} must be numeric")
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    return self._error("invalid_feature_value", f"{name} must be numeric")
                if math.isinf(numeric):
                    return self._error("invalid_feature_value", f"{name} cannot be infinite")
                values.append(numeric)
            raw_score = float(self._pipeline.predict_proba(np.asarray([values], dtype=float))[0, 1])
            calibration = self._metadata["calibration"]
            score = float(apply_calibration([raw_score], calibration["method"], calibration["parameters"])[0])
            low = float(self._metadata["low_medium_threshold"])
            high = float(self._metadata["medium_high_threshold"])
            level = "high" if score >= high else "medium" if score >= low else "low"
            return {
                "status": "ok",
                "risk_score": score,
                "risk_level": level,
                "model_version": self._metadata["model_version"],
                "risk_semantics": "estimated_fire_risk",
                "main_factors": self._main_factors(dict(zip(required, values))),
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return self._error("model_artifact_error", str(exc))

    def _main_factors(self, values: Mapping[str, float]) -> list[dict[str, str]]:
        references = self._metadata.get("feature_reference_train_2023_2024", {})
        ranked = self._metadata.get("global_feature_importance", [])
        factors = []
        for item in ranked:
            feature = item.get("feature")
            reference = references.get(feature)
            value = values.get(feature)
            if reference is None or value is None or math.isnan(value):
                continue
            if reference["q25"] <= value <= reference["q75"]:
                continue
            factors.append({"feature": feature, "statement": _factor_statement(feature)})
            if len(factors) == 3:
                break
        return factors

    @staticmethod
    def _error(code: str, message: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
        error = {"code": code, "message": message}
        if details:
            error["details"] = dict(details)
        return {"status": "error", "risk_score": None, "risk_level": None, "risk_semantics": "estimated_fire_risk", "error": error}


def _factor_statement(feature: str) -> str:
    if feature.startswith("fires_within") or feature.startswith("days_since_previous_firms"):
        return "Recent historical fire activity nearby was associated with the model output."
    if any(token in feature for token in ("temperature", "humidity", "wind", "precipitation")):
        return "Pre-event weather conditions were associated with the model output."
    if feature.startswith("land_cover_"):
        return "Land-cover context influenced the statistical estimate."
    if feature in {"elevation_m", "slope_degrees"}:
        return "Terrain context influenced the statistical estimate."
    return "Seasonal timing was associated with the model output."


PredictionAgent = FireRiskPredictionAgent


def main() -> None:
    parser = argparse.ArgumentParser(description="Score one fully prepared fire-risk feature payload")
    parser.add_argument("features_json", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS_PATH)
    args = parser.parse_args()
    payload = json.loads(args.features_json.read_text(encoding="utf-8"))
    result = FireRiskPredictionAgent(args.model, args.thresholds).predict(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
