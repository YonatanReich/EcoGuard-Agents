"""Immutable policy shared by Air Pollution Trend training and inference."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

from sklearn.linear_model import SGDClassifier

TrendLabel = Literal["FALLING", "STABLE", "RISING"]

TREND_LABELS: tuple[TrendLabel, ...] = ("FALLING", "STABLE", "RISING")
TREND_LABEL_TO_INT: Mapping[TrendLabel, int] = MappingProxyType(
    {label: index for index, label in enumerate(TREND_LABELS)}
)

TREND_RANDOM_SEED = 20260915
TREND_HORIZON_MINUTES = 30
TREND_MINIMUM_HISTORY_COVERAGE = 0.75
TREND_PREPROCESSING_VERSION = "standardized-causal-plus-training-one-hot-identity-v1"
TREND_FINAL_ARTIFACT_VERSION = "air-pollution-trend-sgd-bundle-v1"
TREND_EPSILON_POLICY_VERSION = "training-2021-2023-series-mad-1.4826-v1"
TREND_EPSILON_SCALE_MULTIPLIER = 1.4826
TREND_FINAL_TRAIN_YEARS = (2021, 2022, 2023)
TREND_FINAL_TRAINING_START = "2021-01-01T00:00:00+02:00"
TREND_FINAL_TRAINING_END = "2024-01-01T00:00:00+02:00"


@dataclass(frozen=True)
class TrendSGDConfiguration:
    """Complete deterministic SGD policy for training and artifact validation."""

    name: str
    weighted: bool
    epochs: int
    learning_rate: str
    include_identity: bool = True
    eta0: float = 0.0
    power_t: float = 0.5
    alpha: float = 0.0001

    def __post_init__(self) -> None:
        if self.epochs < 1 or self.learning_rate not in {
            "optimal",
            "constant",
            "invscaling",
        }:
            raise ValueError("unsupported deterministic SGD candidate")
        if self.learning_rate != "optimal" and self.eta0 <= 0:
            raise ValueError("constant/invscaling schedules require eta0")

    def classifier(self) -> SGDClassifier:
        return SGDClassifier(
            loss="log_loss",
            penalty="l2",
            alpha=self.alpha,
            fit_intercept=True,
            max_iter=1,
            tol=None,
            shuffle=False,
            random_state=TREND_RANDOM_SEED,
            average=True,
            learning_rate=self.learning_rate,
            eta0=self.eta0,
            power_t=self.power_t,
        )


LOCKED_TREND_SGD_CONFIGURATIONS: Mapping[str, TrendSGDConfiguration] = (
    MappingProxyType(
        {
            "NO2": TrendSGDConfiguration(
                "phase2b_balanced_optimal_3epoch", True, 3, "optimal"
            ),
            "O3": TrendSGDConfiguration(
                "phase2b_unweighted_invscaling_3epoch",
                False,
                3,
                "invscaling",
                eta0=0.01,
                power_t=0.25,
            ),
            "PM2.5": TrendSGDConfiguration(
                "phase2b_unweighted_invscaling_3epoch",
                False,
                3,
                "invscaling",
                eta0=0.01,
                power_t=0.25,
            ),
            "SO2": TrendSGDConfiguration(
                "phase2b_unweighted_optimal_3epoch", False, 3, "optimal"
            ),
        }
    )
)

APPROVED_TREND_MODEL_POLLUTANTS = frozenset(LOCKED_TREND_SGD_CONFIGURATIONS)
TREND_ARTIFACT_FILENAMES: Mapping[str, str] = MappingProxyType(
    {
        "NO2": "no2.joblib",
        "O3": "o3.joblib",
        "PM2.5": "pm2_5.joblib",
        "SO2": "so2.joblib",
    }
)
SUPPORTED_TREND_POLLUTANTS = APPROVED_TREND_MODEL_POLLUTANTS | {"PM10"}
UNAVAILABLE_TREND_POLLUTANTS: Mapping[str, str] = MappingProxyType(
    {"PM10": "no_accepted_model"}
)
