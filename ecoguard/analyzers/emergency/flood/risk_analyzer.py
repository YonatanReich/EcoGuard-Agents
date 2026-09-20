"""Deterministic operational risk for already detected Flood incidents."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from ecoguard.analyzers.emergency.flood.event_analysis_schemas import (
    FloodEventAnalysis,
    HydrometricStationState,
)
from ecoguard.analyzers.emergency.flood.risk_analysis_schemas import (
    FloodRiskAssessment,
)
from ecoguard.analyzers.emergency.flood.risk_scale import flood_operational_risk


class FloodRiskAnalyzer:
    """Assess current operational severity; never predict Flood occurrence."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._clock = clock

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Flood risk analyzer clock must carry a UTC offset")
        return value.astimezone(timezone.utc)

    def analyze(
        self, analysis: FloodEventAnalysis | Mapping[str, Any]
    ) -> FloodRiskAssessment:
        event = FloodEventAnalysis.model_validate(analysis)
        state = event.current_state
        change = event.change_assessment
        if event.status == "unavailable" or state is None or change is None:
            return FloodRiskAssessment(
                metadata={
                    "timestamp": self._now(),
                    "analysis_status": "unavailable",
                    "reason": "flood_event_analysis_unavailable",
                },
                event_id=event.incident_id,
                evidence_gaps=list(event.evidence_gaps),
                limitations=list(event.limitations),
                error="flood_event_analysis_unavailable",
            )

        try:
            risk_score, risk_level = flood_operational_risk(state.severity_level)
        except ValueError:
            return FloodRiskAssessment(
                metadata={
                    "timestamp": self._now(),
                    "analysis_status": "unavailable",
                    "reason": "active_flood_severity_unavailable",
                },
                event_id=event.incident_id,
                hydrologic_severity_level=state.severity_level,
                return_period_years=state.return_period_years,
                alert_level=state.alert_level,
                change_type=change.change_type,
                evidence_gaps=[
                    *event.evidence_gaps,
                    "No active Q10-or-higher Flood severity was available.",
                ],
                limitations=list(event.limitations),
                error="active_flood_severity_unavailable",
            )

        primary = next(
            (
                station
                for station in state.stations
                if station.station_id == state.primary_station_id
            ),
            None,
        )
        gaps = list(event.evidence_gaps)
        if primary is None or primary.confidence is None:
            gaps.append("Primary hydrometric signal confidence was not provided.")
        confidence = self._confidence(primary)
        status = "partial" if event.status == "partial" or gaps else "success"
        drivers = self._drivers(event, primary)
        q_label = (
            f"Q{state.return_period_years}"
            if state.return_period_years is not None
            else f"severity {state.severity_level}"
        )
        return FloodRiskAssessment(
            metadata={
                "timestamp": self._now(),
                "analysis_status": status,
                "reason": "evidence_gaps_present" if status == "partial" else None,
            },
            event_id=event.incident_id,
            location=(
                {"latitude": primary.latitude, "longitude": primary.longitude}
                if primary is not None
                and primary.latitude is not None
                and primary.longitude is not None
                else None
            ),
            risk_score=risk_score,
            risk_level=risk_level,
            confidence=confidence,
            hydrologic_severity_level=state.severity_level,
            return_period_years=state.return_period_years,
            alert_level=state.alert_level,
            change_type=change.change_type,
            primary_drivers=drivers,
            explanation=(
                f"Detected Flood incident {event.incident_id} is currently at "
                f"{q_label}, mapped to operational risk {risk_score}/100 "
                f"({risk_level}) on the shared emergency scale."
            ),
            evidence_gaps=list(dict.fromkeys(gaps)),
            limitations=list(event.limitations),
        )

    @staticmethod
    def _confidence(primary: HydrometricStationState | None) -> str:
        value = primary.confidence if primary is not None else None
        if value is not None and value >= 0.8:
            return "high"
        if value is not None and value >= 0.5:
            return "medium"
        return "low"

    @staticmethod
    def _drivers(
        event: FloodEventAnalysis,
        primary: HydrometricStationState | None,
    ) -> list[str]:
        state = event.current_state
        change = event.change_assessment
        if state is None or change is None:
            return []
        q_label = (
            f"Q{state.return_period_years} threshold"
            if state.return_period_years is not None
            else f"hydrologic severity {state.severity_level}"
        )
        drivers = [
            f"{q_label} observed at station {state.primary_station_id}",
            f"Operational alert state is {state.alert_level}",
        ]
        progression = event.progression_assessment
        if progression is not None and progression.trend != "unknown":
            drivers.append(f"Observed discharge trend is {progression.trend}")
        if change.change_type == "initial":
            drivers.append(
                f"Initial detected state includes {state.station_count} station(s)"
            )
        elif change.new_station_ids:
            drivers.append(
                f"Evidence expanded to {len(change.new_station_ids)} new station(s)"
            )
        if change.change_type != "initial" and change.new_cell_ids:
            drivers.append(
                f"Observed footprint expanded to {len(change.new_cell_ids)} new cell(s)"
            )
        if primary is not None and primary.confidence is not None:
            drivers.append(
                f"Primary hydrometric signal confidence is {primary.confidence:.2f}"
            )
        return drivers[:8]


__all__ = ["FloodRiskAnalyzer"]
