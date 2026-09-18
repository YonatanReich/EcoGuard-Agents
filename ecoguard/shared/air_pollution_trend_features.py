"""Pure causal features and auditable +30 minute Air Pollution targets."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal, Mapping, Sequence

from ecoguard.shared.air_pollution_history import (
    AirPollutionSeriesIdentity,
    HistoricalAirPollutionObservation,
)

TREND_FEATURE_POLICY_VERSION = "air-pollution-causal-features-v1"
TREND_TARGET_VERSION = "air-pollution-median-25-30-35-v1"
STABILITY_BAND_METHOD_VERSION = "training-series-adjacent-difference-mad-v1"
LOOKBACK_MINUTES = 120
FUTURE_WINDOW_MINUTES = 35
MINIMUM_EMBARGO_MINUTES = LOOKBACK_MINUTES + FUTURE_WINDOW_MINUTES
LAG_MINUTES = (5, 10, 15, 20, 30, 45, 60, 90, 120)
ROLLING_MINUTES = (15, 30, 60, 120)
SLOPE_MINUTES = (15, 30, 60)
FUTURE_OFFSETS_MINUTES = (25, 30, 35)
PROVIDER_TIMEZONE = timezone(timedelta(hours=2))

TrendLabel = Literal["RISING", "STABLE", "FALLING"]


def _feature_columns() -> tuple[str, ...]:
    columns = ["current_concentration"]
    for minutes in LAG_MINUTES:
        columns.extend((
            f"lag_{minutes}m",
            f"change_from_lag_{minutes}m",
            f"lag_{minutes}m_missing",
        ))
    for minutes in ROLLING_MINUTES:
        columns.extend((
            f"rolling_mean_{minutes}m",
            f"rolling_median_{minutes}m",
            f"rolling_std_{minutes}m",
            f"valid_count_{minutes}m",
            f"coverage_ratio_{minutes}m",
        ))
    columns.extend(f"slope_{minutes}m_per_minute" for minutes in SLOPE_MINUTES)
    columns.extend((
        "minutes_since_previous_valid",
        "hour_sin", "hour_cos",
        "day_of_week_sin", "day_of_week_cos",
        "month", "month_sin", "month_cos", "season",
    ))
    return tuple(columns)


FEATURE_COLUMNS = _feature_columns()


@dataclass(frozen=True)
class TrendTarget:
    delta_30: float
    future_concentration: float
    contributing_timestamps: tuple[datetime, ...]
    contributing_offsets_minutes: tuple[int, ...]


@dataclass(frozen=True)
class TrendExample:
    identity: AirPollutionSeriesIdentity
    observed_at: datetime
    unit: str
    features: dict[str, float | int | None]
    target: TrendTarget


@dataclass(frozen=True)
class StabilityBand:
    pollutant: str
    epsilon: float
    version: str
    method_version: str
    training_start: datetime
    training_end: datetime
    series_count: int
    adjacent_difference_count: int
    median_adjacent_difference: float
    adjacent_difference_mad: float
    scale_multiplier: float
    authoritative_instrument_uncertainty: Literal[False] = False
    independent_of_p95: Literal[True] = True

    def label(self, delta_30: float) -> TrendLabel:
        if delta_30 > self.epsilon:
            return "RISING"
        if delta_30 < -self.epsilon:
            return "FALLING"
        return "STABLE"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["training_start"] = self.training_start.isoformat()
        payload["training_end"] = self.training_end.isoformat()
        return payload


class TrainingStabilityBandEstimator:
    """Bounded-memory accumulator for training-only per-series movement MADs."""

    def __init__(
        self,
        pollutant: str,
        *,
        training_start: datetime,
        training_end: datetime,
        scale_multiplier: float = 1.4826,
        version: str = "candidate-v1",
    ) -> None:
        if training_start.utcoffset() is None or training_end.utcoffset() is None:
            raise ValueError("training bounds must carry UTC offsets")
        if training_end <= training_start or scale_multiplier <= 0:
            raise ValueError("invalid training interval or scale multiplier")
        self.pollutant = pollutant
        self.training_start = training_start
        self.training_end = training_end
        self.scale_multiplier = scale_multiplier
        self.version = version
        self._centers: list[float] = []
        self._dispersions: list[float] = []
        self._difference_count = 0

    def add_series(
        self,
        identity: AirPollutionSeriesIdentity,
        observations: Sequence[HistoricalAirPollutionObservation],
    ) -> None:
        if identity.pollutant != self.pollutant:
            return
        selected = sorted(
            (
                item
                for item in observations
                if self.training_start <= item.observed_at < self.training_end
            ),
            key=lambda item: item.observed_at,
        )
        differences = [
            right.value - left.value
            for left, right in zip(selected, selected[1:])
            if right.observed_at - left.observed_at == timedelta(minutes=5)
        ]
        if len(differences) < 2:
            return
        center = float(statistics.median(differences))
        dispersion = float(statistics.median(
            abs(value - center) for value in differences
        ))
        self._centers.append(center)
        self._dispersions.append(dispersion)
        self._difference_count += len(differences)

    def finalize(self) -> StabilityBand:
        if not self._dispersions:
            raise ValueError("insufficient exact adjacent training differences")
        center = float(statistics.median(self._centers))
        mad = float(statistics.median(self._dispersions))
        epsilon = self.scale_multiplier * mad
        if not math.isfinite(epsilon) or epsilon <= 0:
            raise ValueError("training differences do not yield a positive stability band")
        return StabilityBand(
            pollutant=self.pollutant,
            epsilon=epsilon,
            version=self.version,
            method_version=STABILITY_BAND_METHOD_VERSION,
            training_start=self.training_start,
            training_end=self.training_end,
            series_count=len(self._dispersions),
            adjacent_difference_count=self._difference_count,
            median_adjacent_difference=center,
            adjacent_difference_mad=mad,
            scale_multiplier=self.scale_multiplier,
        )


@dataclass(frozen=True)
class ResearchSplitPolicy:
    train_start: datetime = datetime(2021, 1, 1, tzinfo=PROVIDER_TIMEZONE)
    validation_start: datetime = datetime(2024, 1, 1, tzinfo=PROVIDER_TIMEZONE)
    test_start: datetime = datetime(2025, 1, 1, tzinfo=PROVIDER_TIMEZONE)
    archive_end: datetime = datetime(2026, 1, 1, tzinfo=PROVIDER_TIMEZONE)
    embargo_minutes: int = MINIMUM_EMBARGO_MINUTES

    def __post_init__(self) -> None:
        if self.embargo_minutes < MINIMUM_EMBARGO_MINUTES:
            raise ValueError(f"embargo must be at least {MINIMUM_EMBARGO_MINUTES} minutes")
        values = (self.train_start, self.validation_start, self.test_start, self.archive_end)
        if any(value.utcoffset() is None for value in values) or tuple(sorted(values)) != values:
            raise ValueError("split boundaries must be aware and chronological")

    def name_at(self, moment: datetime) -> Literal["train", "validation", "test"] | None:
        if self.train_start <= moment < self.validation_start:
            return "train"
        if self.validation_start <= moment < self.test_start:
            return "validation"
        if self.test_start <= moment < self.archive_end:
            return "test"
        return None

    def split_for_example(self, observed_at: datetime) -> tuple[str | None, str | None]:
        """Return a split or an explicit exclusion reason for one target anchor."""

        if observed_at.utcoffset() is None:
            return None, "naive_timestamp"
        embargo = timedelta(minutes=self.embargo_minutes)
        for boundary in (self.validation_start, self.test_start):
            if boundary - embargo < observed_at < boundary + embargo:
                return None, "split_embargo"
        feature_start = observed_at - timedelta(minutes=LOOKBACK_MINUTES)
        target_end = observed_at + timedelta(minutes=FUTURE_WINDOW_MINUTES)
        split = self.name_at(observed_at)
        if split is None:
            return None, "outside_research_split"
        if self.name_at(feature_start) != split or self.name_at(target_end) != split:
            return None, "split_window_crossing"
        return split, None

    def to_dict(self) -> dict[str, object]:
        return {
            "train": [self.train_start.isoformat(), self.validation_start.isoformat()],
            "validation": [self.validation_start.isoformat(), self.test_start.isoformat()],
            "test": [self.test_start.isoformat(), self.archive_end.isoformat()],
            "embargo_minutes": self.embargo_minutes,
            "feature_lookback_minutes": LOOKBACK_MINUTES,
            "future_window_minutes": FUTURE_WINDOW_MINUTES,
        }


def _index(
    observations: Iterable[HistoricalAirPollutionObservation],
) -> dict[datetime, HistoricalAirPollutionObservation]:
    return {item.observed_at: item for item in observations}


def _rolling(
    ordered: Sequence[HistoricalAirPollutionObservation],
    observed_at: datetime,
    minutes: int,
) -> list[HistoricalAirPollutionObservation]:
    start = observed_at - timedelta(minutes=minutes)
    return [item for item in ordered if start < item.observed_at <= observed_at]


def _slope(points: Sequence[HistoricalAirPollutionObservation]) -> float | None:
    if len(points) < 2:
        return None
    origin = points[0].observed_at
    x = [(item.observed_at - origin).total_seconds() / 60.0 for item in points]
    y = [item.value for item in points]
    x_center, y_center = statistics.fmean(x), statistics.fmean(y)
    denominator = sum((value - x_center) ** 2 for value in x)
    if denominator == 0:
        return None
    return sum((a - x_center) * (b - y_center) for a, b in zip(x, y, strict=True)) / denominator


def build_causal_features(
    observations: Sequence[HistoricalAirPollutionObservation],
    observed_at: datetime,
) -> dict[str, float | int | None]:
    """Build features exclusively from values whose timestamps are <= ``t``."""

    if observed_at.utcoffset() is None:
        raise ValueError("observed_at must carry a UTC offset")
    causal = sorted(
        (item for item in observations if item.observed_at <= observed_at),
        key=lambda item: item.observed_at,
    )
    values_at = _index(causal)
    current = values_at.get(observed_at)
    if current is None:
        raise ValueError("current observation is unavailable")
    features: dict[str, float | int | None] = {
        "current_concentration": current.value,
    }
    for minutes in LAG_MINUTES:
        lag = values_at.get(observed_at - timedelta(minutes=minutes))
        features[f"lag_{minutes}m"] = None if lag is None else lag.value
        features[f"change_from_lag_{minutes}m"] = (
            None if lag is None else current.value - lag.value
        )
        features[f"lag_{minutes}m_missing"] = int(lag is None)

    for minutes in ROLLING_MINUTES:
        points = _rolling(causal, observed_at, minutes)
        values = [item.value for item in points]
        expected = minutes // 5
        features[f"rolling_mean_{minutes}m"] = statistics.fmean(values) if values else None
        features[f"rolling_median_{minutes}m"] = statistics.median(values) if values else None
        features[f"rolling_std_{minutes}m"] = (
            statistics.stdev(values) if len(values) > 1 else 0.0 if values else None
        )
        features[f"valid_count_{minutes}m"] = len(values)
        features[f"coverage_ratio_{minutes}m"] = len(values) / expected

    for minutes in SLOPE_MINUTES:
        features[f"slope_{minutes}m_per_minute"] = _slope(
            _rolling(causal, observed_at, minutes)
        )

    previous = [item for item in causal if item.observed_at < observed_at]
    features["minutes_since_previous_valid"] = (
        None
        if not previous
        else (observed_at - previous[-1].observed_at).total_seconds() / 60.0
    )
    local = observed_at.astimezone(PROVIDER_TIMEZONE)
    hour = local.hour + local.minute / 60.0
    features["hour_sin"] = math.sin(2 * math.pi * hour / 24)
    features["hour_cos"] = math.cos(2 * math.pi * hour / 24)
    features["day_of_week_sin"] = math.sin(2 * math.pi * local.weekday() / 7)
    features["day_of_week_cos"] = math.cos(2 * math.pi * local.weekday() / 7)
    features["month"] = local.month
    features["month_sin"] = math.sin(2 * math.pi * (local.month - 1) / 12)
    features["month_cos"] = math.cos(2 * math.pi * (local.month - 1) / 12)
    features["season"] = (local.month % 12) // 3
    if tuple(features) != FEATURE_COLUMNS:
        raise RuntimeError("feature schema order changed")
    return features


def build_target(
    observations: Sequence[HistoricalAirPollutionObservation],
    observed_at: datetime,
) -> TrendTarget | None:
    values_at = _index(observations)
    current = values_at.get(observed_at)
    if current is None:
        raise ValueError("current observation is unavailable")
    contributors = []
    offsets = []
    for minutes in FUTURE_OFFSETS_MINUTES:
        item = values_at.get(observed_at + timedelta(minutes=minutes))
        if item is not None:
            contributors.append(item)
            offsets.append(minutes)
    if len(contributors) < 2:
        return None
    future = float(statistics.median(item.value for item in contributors))
    return TrendTarget(
        delta_30=future - current.value,
        future_concentration=future,
        contributing_timestamps=tuple(item.observed_at for item in contributors),
        contributing_offsets_minutes=tuple(offsets),
    )


def build_trend_example(
    observations: Sequence[HistoricalAirPollutionObservation],
    observed_at: datetime,
) -> TrendExample | None:
    values_at = _index(observations)
    current = values_at.get(observed_at)
    if current is None:
        raise ValueError("current observation is unavailable")
    target = build_target(observations, observed_at)
    if target is None:
        return None
    return TrendExample(
        identity=current.identity,
        observed_at=observed_at,
        unit=current.unit,
        features=build_causal_features(observations, observed_at),
        target=target,
    )


def estimate_training_stability_band(
    pollutant: str,
    series: Mapping[
        AirPollutionSeriesIdentity, Sequence[HistoricalAirPollutionObservation]
    ] | Iterable[
        tuple[AirPollutionSeriesIdentity, Sequence[HistoricalAirPollutionObservation]]
    ],
    *,
    training_start: datetime,
    training_end: datetime,
    scale_multiplier: float = 1.4826,
    version: str = "candidate-v1",
) -> StabilityBand:
    """Estimate a robust candidate band from exact adjacent training readings.

    This is an engineering movement/noise scale, not instrument uncertainty.
    Values outside ``[training_start, training_end)`` cannot affect it.
    """

    estimator = TrainingStabilityBandEstimator(
        pollutant,
        training_start=training_start,
        training_end=training_end,
        scale_multiplier=scale_multiplier,
        version=version,
    )
    items = series.items() if isinstance(series, Mapping) else series
    for identity, observations in sorted(items, key=lambda item: item[0]):
        estimator.add_series(identity, observations)
    return estimator.finalize()


def class_counts(
    deltas: Iterable[float], band: StabilityBand
) -> dict[TrendLabel, int]:
    counts: Counter[TrendLabel] = Counter(band.label(delta) for delta in deltas)
    return {label: counts[label] for label in ("RISING", "STABLE", "FALLING")}
