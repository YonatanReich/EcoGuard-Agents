"""Hydrometric flood transitions based on official discharge thresholds."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from ecoguard.shared.signals import (
    FLOOD,
    HIGH,
    CellLocation,
    CellSignal,
)


HYDROMETRIC_SOURCE = "water_authority_hydrometric_observations"
FLOW_RETURN_PERIODS = (2, 5, 10, 20, 50, 100)
FLOW_THRESHOLD_STATUS_COMPLETE = "complete_thresholds"
OPERATIONAL_FLOW_REGIME_EPHEMERAL = "ephemeral"
OPERATIONAL_FLOW_REGIME_FLOWING = "flowing_baseline"
OPERATIONAL_FLOW_REGIMES = frozenset({
    OPERATIONAL_FLOW_REGIME_EPHEMERAL,
    OPERATIONAL_FLOW_REGIME_FLOWING,
})
DETECTION_RULE_VERSION = 2


@dataclass(frozen=True)
class FloodPolicy:
    lookback: timedelta = timedelta(hours=1)
    maximum_ingestion_lag: timedelta = timedelta(hours=2)
    maximum_future_skew: timedelta = timedelta(minutes=15)
    ephemeral_alert_threshold_m3s: float = 1.0
    maximum_sample_gap: timedelta = timedelta(minutes=30)


def _threshold_vector(station: Mapping[str, Any]) -> tuple[float, ...] | None:
    """Return one valid, strictly increasing Q2-Q100 vector or no signal."""
    if station.get("flow_threshold_status") != FLOW_THRESHOLD_STATUS_COMPLETE:
        return None
    try:
        thresholds = tuple(
            float(station[f"flow_threshold_{period}y_m3s"])
            for period in FLOW_RETURN_PERIODS
        )
    except (KeyError, TypeError, ValueError):
        return None
    if any(value <= 0 for value in thresholds):
        return None
    if any(current <= previous for previous, current in zip(thresholds, thresholds[1:])):
        return None
    return thresholds


def severity_level(discharge: float, thresholds: Sequence[float]) -> int:
    """Count the official Q2-Q100 thresholds crossed by this reading."""
    return sum(discharge >= threshold for threshold in thresholds)


def operational_severity_level(official_threshold_level: int) -> int:
    """Map a confirmed event onto the existing four operational risk bands."""
    if not 0 <= official_threshold_level <= len(FLOW_RETURN_PERIODS):
        raise ValueError("official threshold level must be between 0 and 6")
    if official_threshold_level <= 1:
        return 3
    return min(6, official_threshold_level + 2)


def _severity_hint(level: int) -> str:
    """A plain word for a severity level, for the operator's card."""
    if level >= 5:
        return "critical"
    if level == 4:
        return "high"
    if level == 3:
        return "moderate"
    return "low"


def alert_level(level: int) -> str:
    """Translate Q-threshold severity into the operational alert state."""
    if level >= 5:
        return "emergency"
    if level == 4:
        return "severe"
    if level == 3:
        return "active"
    if level == 2:
        return "monitoring"
    return "none"


StationSample = tuple[datetime, Mapping[str, Any], float, tuple[float, ...], str,]


def _station_samples(
    observations: Iterable[Mapping[str, Any]],
) -> dict[int, list[tuple[datetime, Mapping[str, Any]]]]:
    """Readings grouped by gauge, oldest first."""
    grouped: dict[int, list[tuple[datetime, Mapping[str, Any]]]] = defaultdict(list)
    for observation in observations:
        if observation.get("source") != HYDROMETRIC_SOURCE:
            continue
        for station in (observation.get("payload") or {}).get("stations", []):
            source_station_id = station.get("source_station_id")
            if source_station_id is None:
                continue
            grouped[int(source_station_id)].append(
                (observation["observed_at"], station)
            )
    for samples in grouped.values():
        samples.sort(key=lambda item: item[0])
    return grouped


def _valid_sample(
    sample: tuple[datetime, Mapping[str, Any]],
) -> StationSample | None:
    """One usable classified reading, or None when required data is missing."""
    observed_at, station = sample
    thresholds = _threshold_vector(station)
    flow_regime = station.get("operational_flow_regime")
    discharge = station.get("discharge_m3s")
    if (
        thresholds is None
        or flow_regime not in OPERATIONAL_FLOW_REGIMES
        or discharge is None
    ):
        return None
    try:
        numeric_discharge = float(discharge)
    except (TypeError, ValueError):
        return None
    if numeric_discharge < 0:
        return None
    return observed_at, station, numeric_discharge, thresholds, str(flow_regime)


def _detection_threshold(sample: StationSample, policy: FloodPolicy) -> float:
    """The event threshold for this gauge's operational baseline."""
    if sample[4] == OPERATIONAL_FLOW_REGIME_EPHEMERAL:
        return policy.ephemeral_alert_threshold_m3s
    return sample[3][0]


def _evidence(
    station_id: int,
    previous: StationSample,
    current: StationSample,
    *,
    stream_id: int | None,
    policy: FloodPolicy,
) -> dict[str, Any]:
    """What the pair of readings showed, recorded on the signal."""
    observed_at, _, discharge, thresholds, flow_regime = current
    current_official_level = severity_level(discharge, thresholds)
    current_level = operational_severity_level(current_official_level)
    threshold_index = current_official_level - 1
    return {
        "station_id": station_id,
        "source_station_id": station_id,
        "stream_id": stream_id,
        "timestamp": observed_at.isoformat(),
        "current_discharge": discharge,
        "detection_rule_version": DETECTION_RULE_VERSION,
        "operational_flow_regime": flow_regime,
        "severity_level": current_level,
        "alert_level": alert_level(current_level),
        "current_threshold_m3s": (
            thresholds[threshold_index] if threshold_index >= 0 else None
        ),
        "return_period_years": (
            FLOW_RETURN_PERIODS[threshold_index] if threshold_index >= 0 else None
        ),
        "severity_hint": _severity_hint(current_level),
        "alert_threshold_m3s": _detection_threshold(current, policy),
        "threshold_vector_m3s": list(thresholds),
        "recent_discharges_m3s": [previous[2], discharge],
    }


def _signal(
    cell_id: str,
    station_id: int,
    previous: StationSample,
    current: StationSample,
    *,
    stream_id: int | None,
    policy: FloodPolicy,
) -> CellSignal:
    """The signal for one confirmed threshold crossing."""
    observed_at, station, discharge, _, _ = current
    return CellSignal(
        cell_id=cell_id,
        observed_at=observed_at,
        hazard=FLOOD,
        variable="discharge",
        value=discharge,
        unit="m3/s",
        source=HYDROMETRIC_SOURCE,
        rarity=None,
        direction=HIGH,
        location=CellLocation(
            latitude=float(station["latitude"]),
            longitude=float(station["longitude"]),
            precision_m=100.0,
            method="hydrometric_station",
        ),
        confidence=0.9,
        severity=None,
        evidence=_evidence(
            station_id,
            previous,
            current,
            stream_id=stream_id,
            policy=policy,
        ),
    )


def evaluate_cell(
    cell_id: str,
    observations: list[Mapping[str, Any]],
    policy: FloodPolicy | None = None,
    *,
    stream_ids: Mapping[int, int] | None = None,
    target_observed_at: set[datetime] | None = None,
) -> list[CellSignal]:
    """Return signals for two consecutive readings above the station rule."""
    selected_policy = policy or FloodPolicy()
    signals: list[CellSignal] = []

    for station_id, raw_samples in _station_samples(observations).items():
        previous: StationSample | None = None
        for raw_sample in raw_samples:
            current = _valid_sample(raw_sample)
            if current is None:
                previous = None
                continue

            is_target = target_observed_at is None or current[0] in target_observed_at
            pair_is_consecutive = (
                previous is not None
                and previous[4] == current[4]
                and current[0] - previous[0]
                <= selected_policy.maximum_sample_gap
            )
            if is_target and pair_is_consecutive and previous is not None:
                alert_confirmed = (
                    previous[2] >= _detection_threshold(previous, selected_policy)
                    and current[2] >= _detection_threshold(current, selected_policy)
                )
                stream_id = (stream_ids or {}).get(station_id)

                if alert_confirmed:
                    signals.append(
                        _signal(
                            cell_id,
                            station_id,
                            previous,
                            current,
                            stream_id=stream_id,
                            policy=selected_policy,
                        )
                    )
            previous = current

    signals.sort(key=lambda signal: signal.observed_at)
    return signals
