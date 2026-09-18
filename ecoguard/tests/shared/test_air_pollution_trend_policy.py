"""Shared immutable Trend policy and portable production-boundary tests."""

import ast
from dataclasses import asdict
from pathlib import Path

from ecoguard.analyzers.non_emergency.air_pollution import trend_inference_service
from ecoguard.paths import REPOSITORY_ROOT
from ecoguard.research.training import evaluate_air_pollution_trend_phase2a as phase2a
from ecoguard.research.training import evaluate_air_pollution_trend_phase2b as phase2b
from ecoguard.shared.air_pollution_trend_policy import (
    LOCKED_TREND_SGD_CONFIGURATIONS,
    TREND_ARTIFACT_FILENAMES,
    TREND_FINAL_ARTIFACT_VERSION,
    TREND_FINAL_TRAINING_END,
    TREND_FINAL_TRAINING_START,
    TREND_LABELS,
    TREND_LABEL_TO_INT,
    TREND_MINIMUM_HISTORY_COVERAGE,
    TREND_PREPROCESSING_VERSION,
)


def test_training_reexports_the_single_shared_policy_contract():
    assert phase2a.LABELS is TREND_LABELS
    assert phase2a.LABEL_TO_INT is TREND_LABEL_TO_INT
    assert phase2b.LOCKED_FINAL_CANDIDATES is LOCKED_TREND_SGD_CONFIGURATIONS
    assert phase2b.FINAL_ARTIFACT_VERSION == TREND_FINAL_ARTIFACT_VERSION
    assert phase2b.FINAL_TRAINING_START == TREND_FINAL_TRAINING_START
    assert phase2b.FINAL_TRAINING_END == TREND_FINAL_TRAINING_END
    assert phase2b.MINIMUM_HISTORY_COVERAGE == TREND_MINIMUM_HISTORY_COVERAGE
    assert phase2b.PREPROCESSING_VERSION == TREND_PREPROCESSING_VERSION
    assert tuple(TREND_ARTIFACT_FILENAMES) == ("NO2", "O3", "PM2.5", "SO2")
    assert asdict(LOCKED_TREND_SGD_CONFIGURATIONS["NO2"]) == {
        "name": "phase2b_balanced_optimal_3epoch",
        "weighted": True,
        "epochs": 3,
        "learning_rate": "optimal",
        "include_identity": True,
        "eta0": 0.0,
        "power_t": 0.5,
        "alpha": 0.0001,
    }


def test_production_inference_has_no_research_imports_and_uses_portable_path():
    source = Path(trend_inference_service.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not {
        module for module in imported_modules if module.startswith("ecoguard.research")
    }
    assert trend_inference_service.DEFAULT_ARTIFACT_DIRECTORY.relative_to(
        REPOSITORY_ROOT
    ) == Path("ecoguard/data/generated/ml/air_pollution_trend/final")
