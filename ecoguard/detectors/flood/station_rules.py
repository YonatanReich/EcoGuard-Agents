"""Minimal hydrometric flood detection based on official discharge thresholds."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence


HYDROMETRIC_SOURCE = "water_authority_hydrometric_observations"
FLOOD_SOURCES = (HYDROMETRIC_SOURCE,)
FLOW_RETURN_PERIODS = (2, 5, 10, 20, 50, 100)
FLOW_THRESHOLD_STATUS_COMPLETE = "complete_thresholds"


@dataclass(frozen=True)
class FloodPolicy:
    lookback: timedelta = timedelta(hours=6)
    maximum_ingestion_lag: timedelta = timedelta(hours=2)
    maximum_future_skew: timedelta = timedelta(minutes=15)
    minimum_alert_level: int = 2
    consecutive_samples: int = 2
    maximum_sample_gap: timedelta = timedelta(minutes=30)
    resolution_threshold_ratio: float = 0.8


@dataclass(frozen=True)
class FloodCandidate:
    event_key: str
    candidate_key: str
    cell_id: str
    observed_at: datetime
    latitude: float
    longitude: float
    confidence: float
    severity_hint: str
    location_uncertainty_m: float
    trigger: str
    evidence: dict[str, Any]

    def public(self) -> dict[str, Any]:
        """Return both the lifecycle fields and the compact station result."""
        return {
            "event_key": self.event_key,
            "candidate_key": self.candidate_key,
            "event_type": "flood",
            "detected": True,
            "cell_id": self.cell_id,
            "station_id": self.evidence["station_id"],
            "timestamp": self.observed_at,
            "current_discharge": self.evidence["current_discharge"],
            "severity_level": self.evidence["severity_level"],
            "observed_at": self.observed_at,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "location": {
                "known": True,
                "latitude": self.latitude,
                "longitude": self.longitude,
                "source": "hydrometric_station",
                "uncertainty_m": self.location_uncertainty_m,
            },
            "confidence": self.confidence,
            "severity_hint": self.severity_hint,
            "location_uncertainty_m": self.location_uncertainty_m,
            "trigger": self.trigger,
            "evidence": self.evidence,
        }

    def database_evidence(self) -> dict[str, Any]:
        return dict(self.evidence)


@dataclass(frozen=True)
class FloodResolution:
    event_key: str
    candidate_key: str
    cell_id: str
    observed_at: datetime
    reason: str
    evidence: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "candidate_key": self.candidate_key,
            "event_type": "flood",
            "cell_id": self.cell_id,
            "observed_at": self.observed_at,
            "status": "resolved",
            "reason": self.reason,
            "evidence": self.evidence,
        }


def _threshold_vector(station: Mapping[str, Any]) -> tuple[float, ...] | None:
    """Return one valid, strictly increasing Q2-Q100 vector or no signal."""
    status = station.get("flow_threshold_status")
    if status is not None and status != FLOW_THRESHOLD_STATUS_COMPLETE:
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
    """Map current discharge to level 0-6 using the official threshold vector."""
    return sum(discharge >= threshold for threshold in thresholds)


def _severity_hint(level: int) -> str:
    if level >= 4:
        return "critical"
    if level == 3:
        return "high"
    if level == 2:
        return "moderate"
    return "low"


def _station_samples(
    observations: Iterable[Mapping[str, Any]],
) -> dict[int, list[tuple[datetime, Mapping[str, Any]]]]:
    grouped: dict[int, list[tuple[datetime, Mapping[str, Any]]]] = defaultdict(list)
    for observation in observations:
        if observation.get("source") != HYDROMETRIC_SOURCE:
            continue
        for station in (observation.get("payload") or {}).get("stations", []):
            grouped[int(station["source_station_id"])].append(
                (observation["observed_at"], station)
            )
    for samples in grouped.values():
        samples.sort(key=lambda item: item[0])
    return grouped


def _valid_sample(
    sample: tuple[datetime, Mapping[str, Any]],
) -> tuple[datetime, Mapping[str, Any], float, tuple[float, ...]] | None:
    observed_at, station = sample
    thresholds = _threshold_vector(station)
    discharge = station.get("discharge_m3s")
    if thresholds is None or discharge is None:
        return None
    try:
        numeric_discharge = float(discharge)
    except (TypeError, ValueError):
        return None
    if numeric_discharge < 0:
        return None
    return observed_at, station, numeric_discharge, thresholds


def evaluate_cell(
    cell_id: str,
    observations: list[Mapping[str, Any]],
    policy: FloodPolicy | None = None,
) -> list[FloodCandidate]:
    """Open an alert after two consecutive readings at or above Q5."""
    selected_policy = policy or FloodPolicy()
    candidates: list[FloodCandidate] = []
    for station_id, raw_samples in _station_samples(observations).items():
        # A missing, invalid or ineligible reading breaks persistence.
        valid_tail: list[
            tuple[datetime, Mapping[str, Any], float, tuple[float, ...]]
        ] = []
        for raw_sample in raw_samples:
            sample = _valid_sample(raw_sample)
            if sample is None:
                valid_tail.clear()
            else:
                valid_tail.append(sample)

        required = selected_policy.consecutive_samples
        if len(valid_tail) < required:
            continue
        recent = valid_tail[-required:]
        if any(
            current[0] - previous[0] > selected_policy.maximum_sample_gap
            for previous, current in zip(recent, recent[1:])
        ):
            continue

        levels = [severity_level(sample[2], sample[3]) for sample in recent]
        if min(levels) < selected_policy.minimum_alert_level:
            continue

        observed_at, station, current_discharge, thresholds = recent[-1]
        current_level = levels[-1]
        current_threshold = thresholds[current_level - 1]
        return_period = FLOW_RETURN_PERIODS[current_level - 1]
        evidence = {
            "station_id": station_id,
            "source_station_id": station_id,
            "timestamp": observed_at.isoformat(),
            "current_discharge": current_discharge,
            "severity_level": current_level,
            "previous_severity_level": levels[-2],
            "current_threshold_m3s": current_threshold,
            "return_period_years": return_period,
            "alert_threshold_m3s": thresholds[
                selected_policy.minimum_alert_level - 1
            ],
            "threshold_vector_m3s": list(thresholds),
            "recent_discharges_m3s": [sample[2] for sample in recent],
        }
        candidates.append(
            FloodCandidate(
                event_key=f"flood:gauge:{cell_id}:{station_id}",
                candidate_key=(
                    f"flood:gauge_discharge_threshold:{cell_id}:{station_id}:"
                    f"{observed_at.isoformat()}"
                ),
                cell_id=cell_id,
                observed_at=observed_at,
                latitude=float(station["latitude"]),
                longitude=float(station["longitude"]),
                confidence=0.9,
                severity_hint=_severity_hint(current_level),
                location_uncertainty_m=100.0,
                trigger="gauge_discharge_threshold",
                evidence=evidence,
            )
        )
    return candidates


def _resolution_for_event(
    event: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
    policy: FloodPolicy,
) -> FloodResolution | None:
    evidence = event.get("evidence") or {}
    station_id = evidence.get("station_id", evidence.get("source_station_id"))
    if station_id is None:
        return None
    raw_samples = _station_samples(observations).get(int(station_id), [])
    valid_tail: list[tuple[datetime, Mapping[str, Any], float, tuple[float, ...]]] = []
    for raw_sample in raw_samples:
        if raw_sample[0] <= event["opened_at"]:
            continue
        sample = _valid_sample(raw_sample)
        if sample is None:
            valid_tail.clear()
        else:
            valid_tail.append(sample)

    required = policy.consecutive_samples
    if len(valid_tail) < required:
        return None
    recent = valid_tail[-required:]
    if any(
        current[0] - previous[0] > policy.maximum_sample_gap
        for previous, current in zip(recent, recent[1:])
    ):
        return None
    alert_threshold = recent[-1][3][policy.minimum_alert_level - 1]
    exit_threshold = alert_threshold * policy.resolution_threshold_ratio
    if not all(sample[2] < exit_threshold for sample in recent):
        return None
    return FloodResolution(
        event_key=str(event["event_key"]),
        candidate_key=str(event["candidate_key"]),
        cell_id=str(event["cell_id"]),
        observed_at=recent[-1][0],
        reason="discharge_below_hysteresis_threshold",
        evidence={
            "station_id": int(station_id),
            "alert_threshold_m3s": alert_threshold,
            "exit_threshold_m3s": exit_threshold,
            "recent_discharges_m3s": [sample[2] for sample in recent],
        },
    )


def evaluate_resolutions(
    observations: list[Mapping[str, Any]],
    active_events: Iterable[Mapping[str, Any]],
    policy: FloodPolicy | None = None,
) -> list[FloodResolution]:
    """Close active station alerts after two readings below 80% of Q5."""
    selected_policy = policy or FloodPolicy()
    resolutions: list[FloodResolution] = []
    for event in active_events:
        resolution = _resolution_for_event(event, observations, selected_policy)
        if resolution is not None:
            resolutions.append(resolution)
    return resolutions
