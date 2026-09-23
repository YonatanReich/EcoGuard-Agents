"""Typed boundary for operational risk of an already detected Flood event."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from ecoguard.analyzers.flood.event_analysis_schemas import (
    FloodAlertLevel,
    FloodChangeType,
)
from ecoguard.shared.schemas import risk_level_for_score


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FloodRiskStatus = Literal["success", "partial", "unavailable"]
FloodRiskLevel = Literal["low", "medium", "high", "critical"]
FloodRiskConfidence = Literal["low", "medium", "high"]


class FloodRiskContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FloodRiskMetadata(FloodRiskContract):
    timestamp: AwareDatetime
    agent: Literal["FloodRiskAnalyzer"] = "FloodRiskAnalyzer"
    analysis_status: FloodRiskStatus
    reason: Text | None = None


class FloodRiskLocation(FloodRiskContract):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class FloodRiskAssessment(FloodRiskContract):
    """Operational risk for a Flood that the detector has already established."""

    assessment_version: Literal["flood-risk-assessment-v1"] = (
        "flood-risk-assessment-v1"
    )
    metadata: FloodRiskMetadata
    event_id: Text
    event_type: Literal["flood"] = "flood"
    location: FloodRiskLocation | None = None
    risk_score: int | None = Field(default=None, ge=0, le=100)
    risk_level: FloodRiskLevel | None = None
    risk_semantics: Literal["detected_event_operational_risk"] = (
        "detected_event_operational_risk"
    )
    confidence: FloodRiskConfidence | None = None
    hydrologic_severity_level: int | None = Field(default=None, ge=0, le=6)
    return_period_years: Literal[2, 5, 10, 20, 50, 100] | None = None
    alert_level: FloodAlertLevel | None = None
    change_type: FloodChangeType | None = None
    primary_drivers: list[Text] = Field(default_factory=list, max_length=8)
    explanation: Text | None = None
    evidence_gaps: list[Text] = Field(default_factory=list, max_length=16)
    limitations: list[Text] = Field(default_factory=list, max_length=24)
    error: Text | None = None

    @model_validator(mode="after")
    def _coherent_status(self) -> "FloodRiskAssessment":
        if self.metadata.analysis_status == "unavailable":
            if any(
                value is not None
                for value in (self.risk_score, self.risk_level, self.confidence)
            ):
                raise ValueError("unavailable Flood risk cannot contain a score")
            return self

        if (
            self.risk_score is None
            or self.risk_level is None
            or self.confidence is None
            or self.explanation is None
            or not self.primary_drivers
        ):
            raise ValueError("available Flood risk requires a complete assessment")
        if self.risk_level != risk_level_for_score(self.risk_score):
            raise ValueError("Flood risk level must match the shared 0-100 scale")
        if self.error is not None:
            raise ValueError("available Flood risk cannot contain an error")
        return self


__all__ = [
    "FloodRiskAssessment",
    "FloodRiskConfidence",
    "FloodRiskLevel",
    "FloodRiskLocation",
    "FloodRiskMetadata",
]
