from __future__ import annotations

import inspect
import json

import numpy as np

from agents.fire_risk_prediction_agent import FireRiskPredictionAgent
from research.training.calibrate_fire_risk_levels import OUTPUT_PATH
from research.training.train_fire_prediction_landcover_terrain_models import DATASET_PATH, load_dataset


def _payload() -> dict[str, float]:
    metadata = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    row = load_dataset(DATASET_PATH)[0]["_environmental"]
    return {name: float(row[name]) for name in metadata["feature_names"]}


def test_prediction_is_deterministic_structured_and_bounded():
    agent = FireRiskPredictionAgent()
    first = agent.predict(_payload())
    second = agent.predict(_payload())
    assert first == second
    assert first["status"] == "ok"
    assert 0.0 <= first["risk_score"] <= 1.0
    assert first["risk_level"] in {"low", "medium", "high"}
    assert first["risk_semantics"] == "estimated_fire_risk"
    assert isinstance(first["main_factors"], list)


def test_exact_feature_order_matches_saved_metadata():
    agent = FireRiskPredictionAgent()
    metadata = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    assert list(agent.feature_names) == metadata["feature_names"]
    assert len(agent.feature_names) == 44


def test_missing_feature_is_rejected():
    payload = _payload()
    payload.pop(next(iter(payload)))
    result = FireRiskPredictionAgent().predict(payload)
    assert result["status"] == "error"
    assert result["error"]["code"] == "missing_features"


def test_unexpected_feature_is_rejected():
    payload = _payload()
    payload["unknown"] = 1.0
    result = FireRiskPredictionAgent().predict(payload)
    assert result["status"] == "error"
    assert result["error"]["code"] == "unexpected_features"


def test_nan_is_passed_to_pipeline_when_supported():
    payload = _payload()
    payload[next(iter(payload))] = np.nan
    result = FireRiskPredictionAgent().predict(payload)
    assert result["status"] == "ok"


def test_agent_has_no_production_detection_or_network_coupling():
    source = inspect.getsource(inspect.getmodule(FireRiskPredictionAgent))
    assert "fire_detection_agent" not in source
    assert "requests" not in source
    assert "telegram" not in source.lower()
