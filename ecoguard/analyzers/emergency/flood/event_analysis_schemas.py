"""Typed contracts for deterministic Flood event analysis.

The analyzer consumes only hydrometric evidence already persisted on a shared
Coordinator incident.  These models deliberately contain no response plan and
no resource allocation: they describe what the gauges show and whether that
description changed materially since the preceding signal.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FloodAnalysisStatus = Literal["success", "partial", "unavailable"]
FloodAlertLevel = Literal["none", "monitoring", "active", "severe", "emergency"]
DischargeTrend = Literal["rising", "stable", "falling", "unknown"]
FloodChangeType = Literal[
    "initial",
    "escalated",
    "deescalated",
    "updated",
    "no_material_change",
]


class FloodAnalysisContract(BaseModel):
    """Strict base for the analyzer boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HydrometricStationState(FloodAnalysisContract):
    """Latest valid state of one gauge inside the incident."""

    station_id: int = Field(ge=1)
    stream_id: int | None = Field(default=None, ge=1)
    cell_id: Text
    observed_at: AwareDatetime
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    precision_m: float = Field(default=0, ge=0)
    current_discharge_m3s: float = Field(ge=0)
    previous_discharge_m3s: float | None = Field(default=None, ge=0)
    severity_level: int = Field(ge=0, le=6)
    return_period_years: Literal[2, 5, 10, 20, 50, 100] | None = None
    alert_level: FloodAlertLevel
    threshold_vector_m3s: list[float] | None = Field(
        default=None, min_length=6, max_length=6
    )
    confidence: float | None = Field(default=None, ge=0, le=1)


class CurrentHydrologicState(FloodAnalysisContract):
    """Incident-level state formed from the latest signal for every gauge."""

    primary_station_id: int = Field(ge=1)
    observed_at: AwareDatetime
    severity_level: int = Field(ge=0, le=6)
    return_period_years: Literal[2, 5, 10, 20, 50, 100] | None = None
    alert_level: FloodAlertLevel
    station_count: int = Field(ge=1)
    cells: list[Text] = Field(min_length=1)
    stations: list[HydrometricStationState] = Field(min_length=1)


class FloodProgressionAssessment(FloodAnalysisContract):
    """Observed gauge-to-gauge change, not a rainfall or inundation forecast."""

    method: Literal["consecutive_hydrometric_observation_trend"] = (
        "consecutive_hydrometric_observation_trend"
    )
    station_id: int = Field(ge=1)
    trend: DischargeTrend
    previous_discharge_m3s: float | None = Field(default=None, ge=0)
    current_discharge_m3s: float = Field(ge=0)
    discharge_change_m3s: float | None = None


class FloodChangeAssessment(FloodAnalysisContract):
    """Whether the latest signal materially changes the operational picture."""

    change_type: FloodChangeType
    material_change: bool
    previous_severity_level: int | None = Field(default=None, ge=0, le=6)
    current_severity_level: int = Field(ge=0, le=6)
    threshold_transition: Text | None = None
    new_station_ids: list[int] = Field(default_factory=list)
    new_cell_ids: list[Text] = Field(default_factory=list)
    reasons: list[Text] = Field(min_length=1)


class FloodEventAnalysis(FloodAnalysisContract):
    """Complete deterministic analysis for one Coordinator Flood incident."""

    analysis_version: Literal["flood-event-analysis-v1"] = "flood-event-analysis-v1"
    incident_id: Text
    hazard_type: Literal["flood"] = "flood"
    generated_at: AwareDatetime
    status: FloodAnalysisStatus
    current_state: CurrentHydrologicState | None = None
    progression_assessment: FloodProgressionAssessment | None = None
    change_assessment: FloodChangeAssessment | None = None
    evidence_gaps: list[Text] = Field(default_factory=list)
    limitations: list[Text] = Field(min_length=1)
    invalid_signal_count: int = Field(default=0, ge=0)
    duplicate_signal_count: int = Field(default=0, ge=0)


__all__ = [
    "CurrentHydrologicState",
    "DischargeTrend",
    "FloodChangeAssessment",
    "FloodChangeType",
    "FloodEventAnalysis",
    "FloodProgressionAssessment",
    "HydrometricStationState",
]
