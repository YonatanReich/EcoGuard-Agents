import json
from pathlib import Path

import joblib

from ecoguard.research.datasets.build_historical_landcover_terrain_features import LAND_COVER_FEATURES, TERRAIN_FEATURES
from ecoguard.research.training.train_fire_prediction_landcover_terrain_models import (
    ABLATIONS, FULL_FEATURES, assert_feature_allowlist,
)
from ecoguard.research.training.train_fire_prediction_environmental_models import FULL_FEATURES as CURRENT_FEATURES
from ecoguard.research.training.train_fire_prediction_models import FORBIDDEN_FEATURES
from ecoguard.paths import GENERATED


def test_ablation_feature_sets_and_no_forbidden_features():
    assert assert_feature_allowlist() == FULL_FEATURES
    assert not set(FULL_FEATURES) & FORBIDDEN_FEATURES
    assert ABLATIONS["current_enriched"] == CURRENT_FEATURES
    assert ABLATIONS["current_plus_land_cover"] == CURRENT_FEATURES + LAND_COVER_FEATURES
    assert ABLATIONS["current_plus_slope"] == CURRENT_FEATURES + TERRAIN_FEATURES
    assert ABLATIONS["current_plus_land_cover_and_slope"] == FULL_FEATURES


def test_saved_model_feature_order_and_temporal_selection_metadata():
    path = GENERATED / "ml" / "fire_prediction_landcover_terrain_model.joblib"
    if path.exists():
        bundle = joblib.load(path); metadata = bundle["metadata"]
        assert metadata["feature_names"] == list(FULL_FEATURES)
        assert metadata["train_years"] == [2023, 2024]
        assert metadata["validation_year"] == 2025
        assert metadata["test_year"] == 2026


def test_saved_metrics_select_model_from_validation_only():
    path = GENERATED / "ml" / "fire_prediction_landcover_terrain_metrics.json"
    if path.exists():
        metrics = json.loads(path.read_text(encoding="utf-8")); comparison = metrics["full_validation_model_comparison"]
        selected = max(comparison, key=lambda name: (comparison[name]["selected_threshold_metrics"]["pr_auc"], comparison[name]["selected_threshold_metrics"]["f1"], comparison[name]["selected_threshold_metrics"]["recall"], name != "dummy"))
        assert metrics["metadata"]["selected_model_type"] == selected
