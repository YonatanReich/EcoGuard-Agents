"""Shared immutable Trend policy and portable production-boundary tests."""

import ast
from dataclasses import asdict
from pathlib import Path

from ecoguard.analyzers.air_pollution import trend_inference_service
from ecoguard.paths import REPOSITORY_ROOT
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


def test_the_locked_trend_policy_is_unchanged():
    """The trend model's configuration is frozen; this is what pins it.

    It used to also assert that the phase2a/phase2b training scripts re-exported
    these constants. Those scripts were one-off experiments with no production
    importer and were removed; the constants they locked are still live, so the
    assertions that matter are kept.
    """
    assert TREND_LABELS and TREND_LABEL_TO_INT
    assert TREND_FINAL_TRAINING_START < TREND_FINAL_TRAINING_END
    assert TREND_FINAL_ARTIFACT_VERSION
    assert TREND_MINIMUM_HISTORY_COVERAGE > 0
    assert TREND_PREPROCESSING_VERSION
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
