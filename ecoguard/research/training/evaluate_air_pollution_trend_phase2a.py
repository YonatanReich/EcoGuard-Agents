"""Training-only audit and 2024 validation for Air Pollution Trend Phase 2A.

The command reads the existing five-minute cache directly.  It never reads a
2025 cache file, materializes the national feature dataset, or saves a model.
"""

from __future__ import annotations

import argparse
import calendar
import json
import math
import time
import warnings
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import sklearn
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

from ecoguard.paths import GENERATED
from ecoguard.research.datasets.build_air_pollution_trend_dataset import (
    DEFAULT_CACHE,
    SUPPORTED_POLLUTANTS,
    select_series,
)
from ecoguard.shared.air_pollution_history import (
    AirPollutionSeriesIdentity,
    HistoricalAirPollutionObservation,
    read_history_month,
)
from ecoguard.shared.air_pollution_trend_features import (
    FEATURE_COLUMNS,
    LAG_MINUTES,
    LOOKBACK_MINUTES,
    PROVIDER_TIMEZONE,
    ROLLING_MINUTES,
    SLOPE_MINUTES,
    STABILITY_BAND_METHOD_VERSION,
    TREND_FEATURE_POLICY_VERSION,
    TREND_TARGET_VERSION,
    TrainingStabilityBandEstimator,
)
from ecoguard.shared.air_pollution_trend_policy import (
    TREND_EPSILON_POLICY_VERSION,
    TREND_EPSILON_SCALE_MULTIPLIER,
    TREND_LABELS,
    TREND_LABEL_TO_INT,
    TREND_RANDOM_SEED,
)

PHASE2A_VERSION = "air-pollution-trend-phase2a-v1"
EPSILON_VERSION = TREND_EPSILON_POLICY_VERSION
TRAINING_START = datetime(2021, 1, 1, tzinfo=PROVIDER_TIMEZONE)
TRAINING_END = datetime(2024, 1, 1, tzinfo=PROVIDER_TIMEZONE)
VALIDATION_START = TRAINING_END
VALIDATION_END = datetime(2025, 1, 1, tzinfo=PROVIDER_TIMEZONE)
SELECTED_EPSILON_MULTIPLIER = TREND_EPSILON_SCALE_MULTIPLIER
SENSITIVITY_MULTIPLIERS = (1.0, 1.4826, 2.0)
LABELS = TREND_LABELS
LABEL_TO_INT = TREND_LABEL_TO_INT
NAIVE_BASELINE_NAMES = (
    "majority_class",
    "always_stable",
    "last_5_minute_direction",
    "trailing_30_minute_slope_direction",
    "linear_slope_extrapolation_30m",
)
DEFAULT_OUTPUT = GENERATED / "ml" / "air_pollution_trend" / "phase2a"
RANDOM_SEED = TREND_RANDOM_SEED


class Phase2AError(RuntimeError):
    """The audit/evaluation cannot proceed without violating its contract."""


@dataclass(frozen=True)
class YearArrays:
    year: int
    values: np.ndarray
    central_positions: np.ndarray
    current_values: np.ndarray
    target_values: np.ndarray
    deltas: np.ndarray
    target_eligible: np.ndarray
    history_counts: np.ndarray


@dataclass(frozen=True)
class FeatureBatch:
    """One bounded identity/year feature batch shared by research stages."""

    identity: AirPollutionSeriesIdentity
    arrays: YearArrays
    mask: np.ndarray
    x: np.ndarray
    y: np.ndarray


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    return (
        datetime(year, 1, 1, tzinfo=PROVIDER_TIMEZONE),
        datetime(year + 1, 1, 1, tzinfo=PROVIDER_TIMEZONE),
    )


def _files_for_years(files: Sequence[Path], years: set[int]) -> list[Path]:
    selected = []
    for path in files:
        try:
            year = int(path.name[:4])
        except ValueError:
            raise Phase2AError(f"malformed cache filename: {path.name}") from None
        if year == 2025:
            continue
        if year in years:
            selected.append(path)
    return sorted(selected)


def load_series(
    expected: AirPollutionSeriesIdentity,
    files: Sequence[Path],
    years: set[int],
) -> list[HistoricalAirPollutionObservation]:
    if 2025 in years or any(year < 2021 or year > 2024 for year in years):
        raise Phase2AError("only 2021-2024 cache access is permitted")
    observations: list[HistoricalAirPollutionObservation] = []
    for path in _files_for_years(files, years):
        month = read_history_month(path)
        if month.year == 2025:
            raise Phase2AError("2025 cache access is forbidden in Phase 2A")
        if month.identity != expected:
            raise Phase2AError(f"cache identity mismatch: {path}")
        observations.extend(month.observations)
    return sorted(observations, key=lambda item: item.observed_at)


def _allowed_anchor_mask(year: int, count: int) -> np.ndarray:
    allowed = np.ones(count, dtype=bool)
    # The archive begins at 2021-01-01, so the first feature window is absent.
    if year == 2021:
        allowed[: LOOKBACK_MINUTES // 5] = False
    # Symmetric 155-minute embargo around the train/validation boundaries.
    if year in (2023, 2024):
        allowed[-30:] = False
    if year == 2024:
        allowed[:31] = False
    return allowed


def build_year_arrays(
    observations: Sequence[HistoricalAirPollutionObservation],
    year: int,
    *,
    allowed_anchor_mask: Callable[[int, int], np.ndarray] = _allowed_anchor_mask,
) -> YearArrays:
    if year not in (2021, 2022, 2023, 2024):
        raise Phase2AError("Phase 2A supports only 2021-2024")
    start, end = _year_bounds(year)
    slots = int((end - start).total_seconds() // 300)
    halo_before = LOOKBACK_MINUTES // 5
    halo_after = 35 // 5
    extended_start = start - timedelta(minutes=LOOKBACK_MINUTES)
    values = np.full(slots + halo_before + halo_after, np.nan, dtype=np.float64)
    for observation in observations:
        offset = (observation.observed_at - extended_start).total_seconds() / 300
        index = int(round(offset))
        if abs(offset - index) > 1e-9 or not 0 <= index < values.size:
            continue
        values[index] = observation.value

    positions = halo_before + np.arange(slots, dtype=np.int64)
    current = values[positions]
    future = np.column_stack([values[positions + offset] for offset in (5, 6, 7)])
    future_counts = np.sum(~np.isnan(future), axis=1)
    ordered_future = np.sort(np.where(np.isnan(future), np.inf, future), axis=1)
    target = np.full(slots, np.nan)
    target[future_counts == 2] = (
        ordered_future[future_counts == 2, 0]
        + ordered_future[future_counts == 2, 1]
    ) / 2.0
    target[future_counts == 3] = ordered_future[future_counts == 3, 1]
    allowed = allowed_anchor_mask(year, slots)
    if allowed.shape != (slots,) or allowed.dtype != np.bool_:
        raise Phase2AError("anchor mask must be a boolean vector for the complete year")
    eligible = allowed & ~np.isnan(current) & (future_counts >= 2)

    history_windows = sliding_window_view(values, 24)[positions - 23]
    history_counts = np.sum(~np.isnan(history_windows), axis=1).astype(np.int16)
    return YearArrays(
        year=year,
        values=values,
        central_positions=positions,
        current_values=current,
        target_values=target,
        deltas=target - current,
        target_eligible=eligible,
        history_counts=history_counts,
    )


def _calendar_features(year: int, slot_indexes: np.ndarray) -> list[np.ndarray]:
    start, _ = _year_bounds(year)
    slot_of_day = slot_indexes % 288
    day_index = slot_indexes // 288
    hour = slot_of_day / 12.0
    weekday = (start.weekday() + day_index) % 7
    day_months = np.asarray([
        (start + timedelta(days=day)).month
        for day in range(366 if calendar.isleap(year) else 365)
    ])
    month = day_months[day_index]
    return [
        np.sin(2 * np.pi * hour / 24),
        np.cos(2 * np.pi * hour / 24),
        np.sin(2 * np.pi * weekday / 7),
        np.cos(2 * np.pi * weekday / 7),
        month.astype(float),
        np.sin(2 * np.pi * (month - 1) / 12),
        np.cos(2 * np.pi * (month - 1) / 12),
        ((month % 12) // 3).astype(float),
    ]


def _window_slope(windows: np.ndarray) -> np.ndarray:
    width = windows.shape[1]
    x = np.arange(width, dtype=float) * 5.0
    valid = ~np.isnan(windows)
    y = np.nan_to_num(windows, nan=0.0)
    n = valid.sum(axis=1).astype(float)
    sum_x = valid @ x
    sum_x2 = valid @ (x * x)
    sum_y = y.sum(axis=1)
    sum_xy = y @ x
    denominator = n * sum_x2 - sum_x * sum_x
    numerator = n * sum_xy - sum_x * sum_y
    result = np.full(len(windows), np.nan)
    usable = (n >= 2) & (denominator != 0)
    result[usable] = numerator[usable] / denominator[usable]
    return result


def feature_matrix(arrays: YearArrays, row_mask: np.ndarray) -> np.ndarray:
    """Vectorized equivalent of the Phase 1 ordered causal feature schema."""

    positions = arrays.central_positions[row_mask]
    slot_indexes = positions - LOOKBACK_MINUTES // 5
    current = arrays.values[positions]
    columns: list[np.ndarray] = [current]
    for minutes in LAG_MINUTES:
        lag = arrays.values[positions - minutes // 5]
        columns.extend((lag, current - lag, np.isnan(lag).astype(float)))
    for minutes in ROLLING_MINUTES:
        width = minutes // 5
        windows = sliding_window_view(arrays.values, width)[positions - width + 1]
        valid = np.sum(~np.isnan(windows), axis=1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            standard_deviation = np.nanstd(windows, axis=1, ddof=1)
        standard_deviation[valid == 1] = 0.0
        columns.extend((
            np.nanmean(windows, axis=1),
            np.nanmedian(windows, axis=1),
            standard_deviation,
            valid.astype(float),
            valid.astype(float) / width,
        ))
    for minutes in SLOPE_MINUTES:
        width = minutes // 5
        windows = sliding_window_view(arrays.values, width)[positions - width + 1]
        columns.append(_window_slope(windows))

    previous_minutes = np.full(len(positions), np.nan)
    for steps in range(1, LOOKBACK_MINUTES // 5 + 1):
        candidate = arrays.values[positions - steps]
        fill = np.isnan(previous_minutes) & ~np.isnan(candidate)
        previous_minutes[fill] = steps * 5.0
    columns.append(previous_minutes)
    columns.extend(_calendar_features(arrays.year, slot_indexes))
    if len(columns) != len(FEATURE_COLUMNS):
        raise RuntimeError("vectorized feature schema differs from Phase 1")
    return np.column_stack(columns).astype(np.float64, copy=False)


def label_deltas(deltas: np.ndarray, epsilon: float) -> np.ndarray:
    labels = np.full(len(deltas), LABEL_TO_INT["STABLE"], dtype=np.int8)
    labels[deltas < -epsilon] = LABEL_TO_INT["FALLING"]
    labels[deltas > epsilon] = LABEL_TO_INT["RISING"]
    return labels


def _percentiles_from_histogram(histogram: Sequence[int]) -> dict[str, float]:
    total = sum(histogram)
    if not total:
        return {}
    cumulative = np.cumsum(histogram)
    output = {}
    for name, fraction in (("p05", .05), ("p25", .25), ("p50", .5), ("p75", .75), ("p95", .95)):
        count = int(np.searchsorted(cumulative, math.ceil(total * fraction), side="left"))
        output[name] = count / 24
    return output


def _gap_summary(observations: Sequence[HistoricalAirPollutionObservation]) -> dict[str, int | float]:
    selected = [item for item in observations if TRAINING_START <= item.observed_at < TRAINING_END]
    gaps = [
        int((right.observed_at - left.observed_at).total_seconds() // 60)
        for left, right in zip(selected, selected[1:])
        if right.observed_at - left.observed_at > timedelta(minutes=5)
    ]
    return {
        "gaps_over_5m": len(gaps),
        "gaps_10_15m": sum(10 <= gap <= 15 for gap in gaps),
        "gaps_20_30m": sum(20 <= gap <= 30 for gap in gaps),
        "gaps_35_60m": sum(35 <= gap <= 60 for gap in gaps),
        "gaps_over_60m": sum(gap > 60 for gap in gaps),
        "missing_slots_inside_gaps": sum(gap // 5 - 1 for gap in gaps),
        "maximum_gap_minutes": max(gaps, default=0),
    }


def run_audit(cache_dir: Path, output_path: Path) -> dict[str, Any]:
    selected, _ = select_series(cache_dir)
    audits = {
        pollutant: {
            "stations": set(), "series": 0, "usable_series": 0,
            "accepted_valid_values": 0, "negative_valid_values": 0,
            "target_eligible_examples": 0, "history_count_histogram": [0] * 25,
            "lag_missing": Counter(), "gaps": Counter(),
        }
        for pollutant in SUPPORTED_POLLUTANTS
    }
    estimators = {
        pollutant: TrainingStabilityBandEstimator(
            pollutant,
            training_start=TRAINING_START,
            training_end=TRAINING_END,
            scale_multiplier=SELECTED_EPSILON_MULTIPLIER,
            version=EPSILON_VERSION,
        )
        for pollutant in SUPPORTED_POLLUTANTS
    }
    started = time.perf_counter()
    for index, (identity, files) in enumerate(selected, start=1):
        observations = load_series(identity, files, {2021, 2022, 2023})
        audit = audits[identity.pollutant]
        audit["series"] += 1
        audit["stations"].add(identity.station_id)
        audit["accepted_valid_values"] += len(observations)
        audit["negative_valid_values"] += sum(item.value < 0 for item in observations)
        estimators[identity.pollutant].add_series(identity, observations)
        eligible_for_series = 0
        for year in (2021, 2022, 2023):
            arrays = build_year_arrays(observations, year)
            mask = arrays.target_eligible
            count = int(mask.sum())
            eligible_for_series += count
            audit["target_eligible_examples"] += count
            audit["history_count_histogram"] = (
                np.asarray(audit["history_count_histogram"])
                + np.bincount(arrays.history_counts[mask], minlength=25)
            ).tolist()
            positions = arrays.central_positions[mask]
            for minutes in LAG_MINUTES:
                audit["lag_missing"][str(minutes)] += int(np.isnan(
                    arrays.values[positions - minutes // 5]
                ).sum())
        if eligible_for_series:
            audit["usable_series"] += 1
        audit["gaps"].update(_gap_summary(observations))
        if index % 10 == 0 or index == len(selected):
            print(f"audit series {index}/{len(selected)}", flush=True)

    result: dict[str, Any] = {
        "phase2a_version": PHASE2A_VERSION,
        "stage": "training_coverage_audit",
        "training_period": [TRAINING_START.isoformat(), TRAINING_END.isoformat()],
        "validation_period": [VALIDATION_START.isoformat(), VALIDATION_END.isoformat()],
        "2025_accessed": False,
        "epsilon_method_version": STABILITY_BAND_METHOD_VERSION,
        "epsilon_multiplier": SELECTED_EPSILON_MULTIPLIER,
        "feature_policy_version": TREND_FEATURE_POLICY_VERSION,
        "target_version": TREND_TARGET_VERSION,
        "pollutants": {},
        "runtime_seconds": time.perf_counter() - started,
    }
    for pollutant in SUPPORTED_POLLUTANTS:
        audit = audits[pollutant]
        total = audit["target_eligible_examples"]
        histogram = audit["history_count_histogram"]
        result["pollutants"][pollutant] = {
            "station_count": len(audit["stations"]),
            "series_count": audit["series"],
            "usable_series_count": audit["usable_series"],
            "accepted_valid_values": audit["accepted_valid_values"],
            "negative_valid_values": audit["negative_valid_values"],
            "target_eligible_examples": total,
            "history_count_histogram": histogram,
            "history_coverage_percentiles": _percentiles_from_histogram(histogram),
            "history_coverage_below": {
                f"{threshold / 24:.6f}": sum(histogram[:threshold])
                for threshold in (12, 18, 20, 22, 24)
            },
            "exact_lag_missing_counts": dict(audit["lag_missing"]),
            "exact_lag_missing_rates": {
                key: value / total for key, value in audit["lag_missing"].items()
            },
            "gap_distribution": dict(audit["gaps"]),
            "stability_band": estimators[pollutant].finalize().to_dict(),
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


class ConfusionAccumulator:
    def __init__(self) -> None:
        self.matrix = np.zeros((3, 3), dtype=np.int64)

    def add(self, truth: np.ndarray, predicted: np.ndarray) -> None:
        np.add.at(self.matrix, (truth.astype(int), predicted.astype(int)), 1)

    def metrics(self) -> dict[str, Any]:
        per_class = {}
        recalls = []
        f1s = []
        for index, label in enumerate(LABELS):
            tp = int(self.matrix[index, index])
            fp = int(self.matrix[:, index].sum() - tp)
            fn = int(self.matrix[index, :].sum() - tp)
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
            recalls.append(recall)
            f1s.append(f1)
            per_class[label] = {"f1": f1, "recall": recall, "support": tp + fn}
        return {
            "macro_f1": float(np.mean(f1s)),
            "balanced_accuracy": float(np.mean(recalls)),
            "per_class": per_class,
            "confusion_matrix": {
                truth: {predicted: int(self.matrix[i, j]) for j, predicted in enumerate(LABELS)}
                for i, truth in enumerate(LABELS)
            },
            "examples": int(self.matrix.sum()),
        }


def _iter_batches(
    cache_dir: Path,
    years: tuple[int, ...],
    epsilon_by_pollutant: dict[str, float],
    minimum_history_coverage: float,
) -> Iterable[tuple[str, YearArrays, np.ndarray, np.ndarray, np.ndarray]]:
    for batch in iter_feature_batches(
        cache_dir,
        years,
        epsilon_by_pollutant,
        minimum_history_coverage,
    ):
        yield (
            batch.identity.pollutant,
            batch.arrays,
            batch.mask,
            batch.x,
            batch.y,
        )


def iter_feature_batches(
    cache_dir: Path,
    years: tuple[int, ...],
    epsilon_by_pollutant: dict[str, float],
    minimum_history_coverage: float,
    *,
    selected_series: Sequence[
        tuple[AirPollutionSeriesIdentity, list[Path]]
    ] | None = None,
    allowed_anchor_mask: Callable[[int, int], np.ndarray] = _allowed_anchor_mask,
) -> Iterable[FeatureBatch]:
    """Stream reusable bounded batches without duplicating Phase 1 construction."""

    if 2025 in years or any(year < 2021 or year > 2024 for year in years):
        raise Phase2AError("only 2021-2024 feature batches are permitted")
    selected = list(selected_series) if selected_series is not None else select_series(cache_dir)[0]
    required_count = math.ceil(24 * minimum_history_coverage)
    for series_index, (identity, files) in enumerate(selected, start=1):
        observations = load_series(identity, files, set(years))
        for year in years:
            arrays = build_year_arrays(
                observations,
                year,
                allowed_anchor_mask=allowed_anchor_mask,
            )
            mask = arrays.target_eligible & (arrays.history_counts >= required_count)
            if not mask.any():
                continue
            x = feature_matrix(arrays, mask)
            deltas = arrays.deltas[mask]
            y = label_deltas(deltas, epsilon_by_pollutant[identity.pollutant])
            yield FeatureBatch(identity, arrays, mask, x, y)
        if series_index % 10 == 0 or series_index == len(selected):
            print(
                f"stream years={years} series {series_index}/{len(selected)}",
                flush=True,
            )


def _direction(values: np.ndarray) -> np.ndarray:
    result = np.full(len(values), LABEL_TO_INT["STABLE"], dtype=np.int8)
    result[values < 0] = LABEL_TO_INT["FALLING"]
    result[values > 0] = LABEL_TO_INT["RISING"]
    return result


def naive_baseline_predictions(
    x: np.ndarray,
    *,
    majority_class: int,
    epsilon: float,
) -> tuple[dict[str, np.ndarray], Counter[str]]:
    """Return the shared deterministic naive predictions and fallback counts."""

    count = len(x)
    predictions = {
        "majority_class": np.full(count, majority_class, dtype=np.int8),
        "always_stable": np.full(count, LABEL_TO_INT["STABLE"], dtype=np.int8),
    }
    fallback: Counter[str] = Counter()
    lag5 = x[:, FEATURE_COLUMNS.index("change_from_lag_5m")]
    missing = np.isnan(lag5)
    predictions["last_5_minute_direction"] = _direction(
        np.nan_to_num(lag5, nan=0.0)
    )
    fallback["last_5_minute_direction"] += int(missing.sum())

    slope = x[:, FEATURE_COLUMNS.index("slope_30m_per_minute")]
    missing = np.isnan(slope)
    predictions["trailing_30_minute_slope_direction"] = _direction(
        np.nan_to_num(slope, nan=0.0)
    )
    predictions["linear_slope_extrapolation_30m"] = label_deltas(
        np.nan_to_num(slope * 30.0, nan=0.0), epsilon
    )
    fallback["trailing_30_minute_slope_direction"] += int(missing.sum())
    fallback["linear_slope_extrapolation_30m"] += int(missing.sum())
    return predictions, fallback


def run_training_validation(
    cache_dir: Path,
    audit_path: Path,
    output_path: Path,
    *,
    minimum_history_coverage: float,
) -> dict[str, Any]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("training_period") != [TRAINING_START.isoformat(), TRAINING_END.isoformat()]:
        raise Phase2AError("audit training period mismatch")
    epsilon = {
        pollutant: float(audit["pollutants"][pollutant]["stability_band"]["epsilon"])
        for pollutant in SUPPORTED_POLLUTANTS
    }
    scalers = {pollutant: StandardScaler() for pollutant in SUPPORTED_POLLUTANTS}
    train_counts = {pollutant: np.zeros(3, dtype=np.int64) for pollutant in SUPPORTED_POLLUTANTS}
    sensitivity = {
        pollutant: {str(value): np.zeros(3, dtype=np.int64) for value in SENSITIVITY_MULTIPLIERS}
        for pollutant in SUPPORTED_POLLUTANTS
    }
    included_train = Counter()
    started = time.perf_counter()

    # Pass 1: training-only preprocessing and exact class/sensitivity counts.
    for pollutant, arrays, mask, x, y in _iter_batches(
        cache_dir, (2021, 2022, 2023), epsilon, minimum_history_coverage
    ):
        scalers[pollutant].partial_fit(x)
        train_counts[pollutant] += np.bincount(y, minlength=3)
        included_train[pollutant] += len(y)
        base_mad = audit["pollutants"][pollutant]["stability_band"]["adjacent_difference_mad"]
        for multiplier in SENSITIVITY_MULTIPLIERS:
            labels = label_deltas(arrays.deltas[mask], float(base_mad) * multiplier)
            sensitivity[pollutant][str(multiplier)] += np.bincount(labels, minlength=3)

    models = {}
    for pollutant in SUPPORTED_POLLUTANTS:
        if np.any(train_counts[pollutant] == 0):
            raise Phase2AError(f"training class absent for {pollutant}")
        models[pollutant] = SGDClassifier(
            loss="log_loss",
            penalty="l2",
            alpha=0.0001,
            fit_intercept=True,
            max_iter=1,
            tol=None,
            shuffle=False,
            random_state=RANDOM_SEED,
            average=True,
        )

    # Pass 2: one deterministic streaming SGD epoch over training only.
    initialized: set[str] = set()
    for pollutant, _arrays, _mask, x, y in _iter_batches(
        cache_dir, (2021, 2022, 2023), epsilon, minimum_history_coverage
    ):
        transformed = scalers[pollutant].transform(x)
        transformed = np.nan_to_num(transformed, nan=0.0, posinf=0.0, neginf=0.0)
        counts = train_counts[pollutant]
        weights = counts.sum() / (3.0 * counts)
        sample_weight = weights[y]
        kwargs = {"classes": np.arange(3)} if pollutant not in initialized else {}
        models[pollutant].partial_fit(
            transformed, y, sample_weight=sample_weight, **kwargs
        )
        initialized.add(pollutant)

    majority = {
        pollutant: int(np.argmax(train_counts[pollutant]))
        for pollutant in SUPPORTED_POLLUTANTS
    }
    names = (*NAIVE_BASELINE_NAMES, "sgd_log_loss")
    metrics = {
        pollutant: {name: ConfusionAccumulator() for name in names}
        for pollutant in SUPPORTED_POLLUTANTS
    }
    fallback = {pollutant: Counter() for pollutant in SUPPORTED_POLLUTANTS}

    # Pass 3: validation only.  No parameter is fit or selected here.
    for pollutant, _arrays, _mask, x, y in _iter_batches(
        cache_dir, (2024,), epsilon, minimum_history_coverage
    ):
        predictions, naive_fallback = naive_baseline_predictions(
            x,
            majority_class=majority[pollutant],
            epsilon=epsilon[pollutant],
        )
        fallback[pollutant].update(naive_fallback)

        transformed = scalers[pollutant].transform(x)
        transformed = np.nan_to_num(transformed, nan=0.0, posinf=0.0, neginf=0.0)
        predictions["sgd_log_loss"] = models[pollutant].predict(transformed)
        for name, predicted in predictions.items():
            metrics[pollutant][name].add(y, predicted)

    result = {
        "phase2a_version": PHASE2A_VERSION,
        "stage": "streaming_linear_baseline_validation",
        "python_environment": {
            "numpy": np.__version__, "sklearn": sklearn.__version__,
        },
        "training_period": [TRAINING_START.isoformat(), TRAINING_END.isoformat()],
        "validation_period": [VALIDATION_START.isoformat(), VALIDATION_END.isoformat()],
        "2025_accessed": False,
        "minimum_history_policy": {
            "window_minutes": 120,
            "minimum_coverage": minimum_history_coverage,
            "minimum_valid_readings": math.ceil(24 * minimum_history_coverage),
        },
        "epsilon": {
            pollutant: audit["pollutants"][pollutant]["stability_band"]
            for pollutant in SUPPORTED_POLLUTANTS
        },
        "sgd": {
            "loss": "log_loss", "penalty": "l2", "alpha": 0.0001,
            "epochs": 1, "shuffle": False, "average": True,
            "random_seed": RANDOM_SEED,
            "imputation": "training-mean-after-StandardScaler_equals_zero",
            "class_weighting": "inverse_training_class_frequency",
            "model_saved": False,
        },
        "training": {
            pollutant: {
                "included_examples": included_train[pollutant],
                "class_counts": {
                    label: int(train_counts[pollutant][index])
                    for index, label in enumerate(LABELS)
                },
                "class_prevalence": {
                    label: float(train_counts[pollutant][index] / train_counts[pollutant].sum())
                    for index, label in enumerate(LABELS)
                },
                "epsilon_sensitivity": {
                    multiplier: {
                        label: int(counts[index])
                        for index, label in enumerate(LABELS)
                    }
                    for multiplier, counts in sensitivity[pollutant].items()
                },
            }
            for pollutant in SUPPORTED_POLLUTANTS
        },
        "validation_metrics": {
            pollutant: {
                name: accumulator.metrics()
                for name, accumulator in metrics[pollutant].items()
            }
            for pollutant in SUPPORTED_POLLUTANTS
        },
        "validation_missing_feature_fallback_counts": {
            pollutant: dict(fallback[pollutant]) for pollutant in SUPPORTED_POLLUTANTS
        },
        "runtime_seconds": time.perf_counter() - started,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("audit", "train-validate"))
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--minimum-history-coverage", type=float, default=0.75)
    args = parser.parse_args(argv)
    if not 0 < args.minimum_history_coverage <= 1:
        raise SystemExit("--minimum-history-coverage must be in (0, 1]")
    audit_path = args.output_dir / "training_coverage_audit.json"
    if args.stage == "audit":
        result = run_audit(args.cache_dir, audit_path)
    else:
        if not audit_path.exists():
            raise SystemExit(f"audit is required first: {audit_path}")
        result = run_training_validation(
            args.cache_dir,
            audit_path,
            args.output_dir / "sgd_validation_results.json",
            minimum_history_coverage=args.minimum_history_coverage,
        )
    print(json.dumps({
        "stage": result["stage"], "runtime_seconds": result["runtime_seconds"],
        "output_dir": str(args.output_dir), "2025_accessed": result["2025_accessed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
