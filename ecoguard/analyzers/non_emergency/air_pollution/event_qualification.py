"""Reusable Air Pollution Path A/Path B event qualification.

This is the existing API publication rule moved behind an Air-Pollution-specific
boundary. It deliberately does not classify p95, health severity, or response
priority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Any

from pydantic import AwareDatetime, TypeAdapter, ValidationError

from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import (
    AirPollutionEventQualification,
)
from ecoguard.shared.signals import AIR_POLLUTION, corroborates

_aware_datetime_adapter = TypeAdapter(AwareDatetime)


@dataclass(frozen=True)
class StoredAirPollutionSignal:
    detection_id: str
    cell_id: str
    observed_at: datetime
    hazard: str
    source: str
    station_id: str
    channel_id: str
    pollutant: str


@dataclass(frozen=True)
class ProjectedAirPollutionIdentity:
    station_id: str
    channel_id: str
    pollutant: str
    observed_at: datetime
    provider: str | None = None


@dataclass(frozen=True)
class MatchingOfficialPollutantIndex:
    station_id: str | None
    channel_id: str | None
    pollutant: str | None
    pollutant_sub_index: float | None


def stored_air_pollution_signals(
    incident: Mapping[str, Any],
) -> list[StoredAirPollutionSignal]:
    signals = incident.get("signals") or incident.get("incident_signals")
    if not isinstance(signals, list):
        return []

    stored = []
    for signal in signals:
        if not isinstance(signal, Mapping) or signal.get("hazard") != AIR_POLLUTION:
            continue
        evidence = signal.get("evidence")
        candidate = (
            evidence.get("correlation_candidate")
            if isinstance(evidence, Mapping)
            else None
        )
        anomaly = candidate.get("anomaly") if isinstance(candidate, Mapping) else None
        detection_id = anomaly.get("detection_id") if isinstance(anomaly, Mapping) else None
        try:
            if not isinstance(detection_id, str) or not detection_id:
                continue
            cell_id = signal["cell_id"]
            source = signal["source"]
            station_id = anomaly["station_id"]
            channel_id = anomaly["channel_id"]
            pollutant = anomaly["pollutant"]
            if not all(
                isinstance(value, str) and value
                for value in (
                    cell_id,
                    source,
                    station_id,
                    channel_id,
                    pollutant,
                )
            ):
                continue
            observed_at = _aware_datetime_adapter.validate_python(
                signal["observed_at"]
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            continue
        stored.append(StoredAirPollutionSignal(
            detection_id=detection_id,
            cell_id=cell_id,
            observed_at=observed_at,
            hazard=AIR_POLLUTION,
            source=source,
            station_id=station_id,
            channel_id=channel_id,
            pollutant=pollutant,
        ))
    return stored


def _corroborating_pairs(incident: Mapping[str, Any]):
    for first, second in combinations(stored_air_pollution_signals(incident), 2):
        if first.detection_id == second.detection_id:
            continue
        try:
            if corroborates(first, second):  # type: ignore[arg-type]
                yield first, second
        except (TypeError, ValueError):
            continue


def _matches_projected_anomaly(
    signal: StoredAirPollutionSignal,
    projected: ProjectedAirPollutionIdentity,
) -> bool:
    return bool(
        signal.station_id == projected.station_id
        and signal.channel_id == projected.channel_id
        and signal.pollutant == projected.pollutant
        and signal.observed_at == projected.observed_at
        and (projected.provider is None or signal.source == projected.provider)
    )


def _path_a(
    incident: Mapping[str, Any],
    projected: ProjectedAirPollutionIdentity,
) -> bool:
    return any(
        first.pollutant == second.pollutant == projected.pollutant
        and (first.source, first.station_id) != (second.source, second.station_id)
        and any(
            _matches_projected_anomaly(signal, projected)
            for signal in (first, second)
        )
        for first, second in _corroborating_pairs(incident)
    )


def _path_b(
    incident: Mapping[str, Any],
    projected: ProjectedAirPollutionIdentity,
    official_index: MatchingOfficialPollutantIndex | None,
) -> bool:
    if (
        official_index is None
        or official_index.pollutant_sub_index is None
        or official_index.pollutant_sub_index >= 0
        or official_index.station_id is None
        or official_index.pollutant is None
        or official_index.channel_id is None
        or official_index.station_id != projected.station_id
        or official_index.pollutant != projected.pollutant
        or official_index.channel_id != projected.channel_id
    ):
        return False

    for first, second in _corroborating_pairs(incident):
        if (
            (first.source, first.station_id) == (second.source, second.station_id)
            and first.station_id == official_index.station_id
            and first.pollutant == second.pollutant == official_index.pollutant
            and first.observed_at != second.observed_at
            and official_index.channel_id in {first.channel_id, second.channel_id}
            and any(
                _matches_projected_anomaly(signal, projected)
                for signal in (first, second)
            )
        ):
            return True
    return False


def qualify_air_pollution_event(
    incident: Mapping[str, Any],
    *,
    projected: ProjectedAirPollutionIdentity,
    official_index: MatchingOfficialPollutantIndex | None,
) -> AirPollutionEventQualification:
    """Apply the established Path A first, then Path B, without changing either."""

    if _path_a(incident, projected):
        return AirPollutionEventQualification(
            qualified=True,
            path="PATH_A",
            reason="same_pollutant_different_station_spatial_corroboration",
        )
    if _path_b(incident, projected, official_index):
        return AirPollutionEventQualification(
            qualified=True,
            path="PATH_B",
            reason="same_station_persistence_with_negative_matching_pollutant_index",
        )
    return AirPollutionEventQualification(
        qualified=False,
        reason="air_pollution_event_qualification_not_satisfied",
    )
