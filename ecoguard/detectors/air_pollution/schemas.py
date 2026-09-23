"""Air-pollution detector boundary for the shared EcoGuard pipeline.

The anomaly record is statistical evidence only.  It deliberately carries no
severity, confidence, health-risk, emergency-routing, or response decision.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from ecoguard.detectors.air_pollution.baseline_schemas import (
    BaselineBucketStatistics,
    BaselineIdentity,
    BaselineVersionProvenance,
    LiveObservationContext,
)
from ecoguard.shared.air_quality_schemas import GeographicCoordinate, PollutantUnit

DETECTOR_BASELINE_FAMILY = "five_minute_observation"
DETECTOR_RULE_VERSION = "air-pollution-five-minute-p95-v1"

DetectionStatus = Literal["NORMAL", "SUSPECTED_ANOMALY", "NOT_EVALUATED"]


class AnomalyContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# Compatibility name used by the existing transport science modules.  This is
# the same strict current contract, not a second anomaly model.
ContractModel = AnomalyContract


class AirPollutionBaselineEvidence(AnomalyContract):
    """Exact baseline bucket and immutable version evidence used by a decision."""

    identity: BaselineIdentity
    month: int = Field(ge=1, le=12)
    hour: int = Field(ge=0, le=23)
    statistics: BaselineBucketStatistics
    version: BaselineVersionProvenance

    @model_validator(mode="after")
    def _require_detector_family(self) -> "AirPollutionBaselineEvidence":
        """Reject evidence built from a baseline this detector does not use."""
        if self.identity.baseline_family != DETECTOR_BASELINE_FAMILY:
            raise ValueError("detector evidence requires five_minute_observation baseline")
        return self


class AirPollutionAnomaly(AnomalyContract):
    """Canonical detector output passed to later Air Pollution pipeline stages."""

    detection_id: str = Field(min_length=1, max_length=200)
    anomaly_type: Literal["air_pollution"] = "air_pollution"
    observed_at: AwareDatetime
    detected_at: AwareDatetime
    location: GeographicCoordinate
    provider: str
    station_id: str
    station_name: str | None = None
    channel_id: str
    pollutant: str
    value: float
    unit: str
    live_observation: LiveObservationContext
    detector_reason: Literal["live_value_above_baseline_p95"]
    detector_rule_version: str
    baseline_evidence: AirPollutionBaselineEvidence

    @model_validator(mode="after")
    def _validate_evidence_identity(self) -> "AirPollutionAnomaly":
        """Reject an anomaly whose evidence describes a different reading."""
        identity = self.baseline_evidence.identity
        if (
            self.provider,
            self.station_id,
            self.channel_id,
            self.pollutant,
            self.unit,
        ) != (
            identity.provider,
            identity.station_id,
            identity.channel_id,
            identity.pollutant,
            identity.canonical_unit,
        ):
            raise ValueError("anomaly identity must exactly match baseline evidence")
        live = self.live_observation
        if (
            self.provider,
            self.station_id,
            self.channel_id,
            self.pollutant,
            self.value,
            self.unit,
            self.observed_at,
            self.location,
        ) != (
            live.provider,
            live.station_id,
            live.channel_id,
            live.pollutant,
            live.value,
            live.measurement_unit,
            live.observed_at,
            live.location,
        ):
            raise ValueError("anomaly fields must exactly match the live observation")
        if self.detected_at < self.observed_at:
            raise ValueError("detected_at cannot precede observed_at")
        return self


class AirPollutionDetectionResult(AnomalyContract):
    """Result for every attempt; only suspected anomalies contain an event."""

    status: DetectionStatus
    reason: str
    detector_rule_version: str
    live_observation: LiveObservationContext | None = None
    baseline_evidence: AirPollutionBaselineEvidence | None = None
    context_reason: str | None = None
    anomaly: AirPollutionAnomaly | None = None

    @model_validator(mode="after")
    def _event_matches_status(self) -> "AirPollutionDetectionResult":
        """Reject a result that claims an anomaly its status does not allow."""
        if (self.status == "SUSPECTED_ANOMALY") != (self.anomaly is not None):
            raise ValueError("only SUSPECTED_ANOMALY may contain an anomaly")
        return self
