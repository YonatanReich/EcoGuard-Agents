"""Normalized Air Pollution Anomaly Detector output.

This module defines the domain boundary between an air-pollution anomaly
detector and the future Coordinator/Strainer::

    Air Pollution Anomaly -> Coordinator -> Incident

An :class:`AirPollutionAnomaly` is evidence that environmental observations
are anomalous.  It is not an incident, emergency classification, human-life
risk assessment, response plan, allocation, or dispatch decision.  The schema
is deliberately independent of collection providers and storage (including
PostGIS), so adapters can normalize their data without leaking source-specific
payloads into the Coordinator contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

PollutantUnit = Literal["µg/m³", "mg/m³", "ng/m³", "ppb", "ppm"]
AnomalySeverity = Literal["low", "medium", "high", "critical"]
DetectionMethod = Literal[
    "reference_threshold",
    "provider_aqi",
    "sustained_condition",
    "historical_baseline",
]

CORE_AIR_POLLUTANTS: frozenset[str] = frozenset(
    {"PM2.5", "PM10", "NO2", "NO", "NOx", "O3", "CO", "SO2"}
)

_POLLUTANT_ALIASES = {
    "PM2.5": "PM2.5",
    "PM25": "PM2.5",
    "PM10": "PM10",
    "NO2": "NO2",
    "NO": "NO",
    "NOX": "NOx",
    "O3": "O3",
    "CO": "CO",
    "SO2": "SO2",
}

# Weather observations belong to the shared weather layer, never the pollutant
# collection. These names are rejected even though they satisfy the safe
# identifier syntax used to admit future pollutant compounds.
_NON_POLLUTANT_CONTEXT_IDS = frozenset(
    {"TEMPERATURE", "HUMIDITY", "PRECIPITATION", "RAIN", "WIND", "WINDSPEED"}
)


class ContractModel(BaseModel):
    """Strict base for anomaly-boundary records."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GeographicCoordinate(ContractModel):
    """Provider-independent WGS84 point."""

    latitude: float = Field(ge=-90, le=90, strict=True)
    longitude: float = Field(ge=-180, le=180, strict=True)


class PolygonBoundary(ContractModel):
    """A simple geographic boundary, without binding to raw GeoJSON payloads."""

    coordinates: list[GeographicCoordinate] = Field(min_length=3)


class AffectedArea(ContractModel):
    """Optional approximate spatial context supplied by a detector.

    A detector may supply a polygon, a radius around the anomaly location, or
    both.  Neither is fabricated when the source cannot establish an area.
    """

    boundary: PolygonBoundary | None = None
    radius_m: float | None = Field(default=None, gt=0, strict=True)
    description: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _require_spatial_description(self) -> "AffectedArea":
        if self.boundary is None and self.radius_m is None:
            raise ValueError("affected_area requires boundary or radius_m")
        return self


class PollutantObservation(ContractModel):
    """One supplied pollutant measurement; absence is represented by no item.

    Known monitoring identifiers are normalized to ``CORE_AIR_POLLUTANTS``.
    Future identifiers may pass when they use a compact chemical/monitoring
    identifier form (for example ``C6H6``), while whitespace, punctuation-heavy
    labels, and weather variables are rejected. ``provider_pollutant_id`` keeps
    the source's exact identifier when it differs from the canonical value.
    """

    pollutant: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z][A-Za-z0-9]*(?:\.[0-9]+)?$",
    )
    provider_pollutant_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    value: float = Field(ge=0, strict=True)
    unit: PollutantUnit
    provider_unit: str | None = Field(default=None, min_length=1, max_length=100)
    observed_at: AwareDatetime | None = None
    source_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("pollutant")
    @classmethod
    def _normalize_pollutant(cls, value: str) -> str:
        normalized = _POLLUTANT_ALIASES.get(value.upper(), value)
        if normalized.upper() in _NON_POLLUTANT_CONTEXT_IDS:
            raise ValueError("weather context cannot be a pollutant observation")
        return normalized

    @field_validator("unit", mode="before")
    @classmethod
    def _normalize_unit(cls, value: object) -> object:
        if value == "ng/m3":
            return "ng/m³"
        return value

    @field_validator("provider_pollutant_id", "provider_unit", "source_id")
    @classmethod
    def _strip_optional_source_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("identifier cannot be blank")
        return stripped


class AnomalySource(ContractModel):
    """Identity and collection metadata for one contributing source."""

    source_id: str = Field(min_length=1, max_length=200)
    source_name: str = Field(min_length=1, max_length=300)
    source_type: str | None = Field(default=None, min_length=1, max_length=100)
    observed_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime | None = None
    reference: str | None = Field(default=None, min_length=1, max_length=1000)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("source_id", "source_name", "source_type", "reference")
    @classmethod
    def _strip_source_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class SupportingEvidence(ContractModel):
    """Auditable evidence associated with the anomaly assessment."""

    evidence_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=200)
    evidence_type: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)
    observed_at: AwareDatetime | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("evidence_id", "source_id", "evidence_type", "summary")
    @classmethod
    def _strip_evidence_text(cls, value: str) -> str:
        return value.strip()


class DetectionAssessment(ContractModel):
    """Optional, auditable details of the deterministic detector assessment."""

    detection_methods: list[DetectionMethod] = Field(default_factory=list)
    window_started_at: AwareDatetime | None = None
    window_ended_at: AwareDatetime | None = None
    aggregation_minutes: int | None = Field(default=None, gt=0)
    valid_sample_count: int | None = Field(default=None, ge=0)
    expected_sample_count: int | None = Field(default=None, ge=1)
    completeness_ratio: float | None = Field(default=None, ge=0, le=1)
    window_complete: bool | None = None
    reference_kind: Literal["target", "environmental", "alert", "other"] | None = None
    reference_value: float | None = Field(default=None, ge=0, strict=True)
    reference_unit: PollutantUnit | None = None
    reference_source: str | None = Field(default=None, min_length=1, max_length=500)
    reference_version: str | None = Field(default=None, min_length=1, max_length=200)
    provider_aqi_value: float | None = Field(default=None, strict=True)
    provider_aqi_category: str | None = Field(default=None, min_length=1, max_length=100)
    baseline_median: float | None = Field(default=None, ge=0, strict=True)
    baseline_deviation: float | None = Field(default=None, ge=0, strict=True)
    freshness_seconds: float | None = Field(default=None, ge=0)
    preliminary: bool = False
    limitations: list[str] = Field(default_factory=list)
    confidence_factors: dict[str, float] = Field(default_factory=dict)
    confidence_caps: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_assessment(self) -> "DetectionAssessment":
        if (
            self.window_started_at is not None
            and self.window_ended_at is not None
            and self.window_ended_at < self.window_started_at
        ):
            raise ValueError("window_ended_at cannot precede window_started_at")
        if self.reference_value is not None and self.reference_unit is None:
            raise ValueError("reference_unit is required with reference_value")
        if self.expected_sample_count and self.valid_sample_count is not None:
            expected_ratio = min(self.valid_sample_count / self.expected_sample_count, 1.0)
            if (
                self.completeness_ratio is not None
                and abs(self.completeness_ratio - expected_ratio) > 1e-9
            ):
                raise ValueError("completeness_ratio does not match sample counts")
        if any(not item.strip() for item in self.limitations):
            raise ValueError("limitations cannot contain blank entries")
        if any(
            not name.strip() or not -1 <= contribution <= 1
            for name, contribution in self.confidence_factors.items()
        ):
            raise ValueError("confidence factors require names and values from -1 to 1")
        if any(
            not name.strip() or not 0 <= cap <= 1
            for name, cap in self.confidence_caps.items()
        ):
            raise ValueError("confidence caps require names and values from 0 to 1")
        return self


class AirPollutionAnomaly(ContractModel):
    """One normalized anomaly detection emitted for Coordinator correlation.

    ``severity`` describes the magnitude of the pollution anomaly only.  It is
    not a human-life risk score or an emergency classification. ``confidence``
    is the detector's bounded confidence in this anomaly record, not confidence
    in any downstream incident or response decision.
    """

    detection_id: str = Field(min_length=1, max_length=200)
    anomaly_type: Literal["air_pollution"] = "air_pollution"
    observed_at: AwareDatetime
    detected_at: AwareDatetime
    location: GeographicCoordinate
    affected_area: AffectedArea | None = None
    pollutant_observations: list[PollutantObservation] = Field(default_factory=list)
    severity: AnomalySeverity
    confidence: float = Field(ge=0, le=1, strict=True)
    explanation: str = Field(min_length=1, max_length=3000)
    anomaly_reasons: list[str] = Field(default_factory=list, max_length=20)
    sources: list[AnomalySource] = Field(min_length=1)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)
    assessment: DetectionAssessment | None = None

    @field_validator("detection_id", "explanation")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("anomaly_reasons")
    @classmethod
    def _validate_reasons(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("anomaly_reasons cannot contain blank entries")
        return stripped

    @model_validator(mode="after")
    def _normalize_and_validate_times(self) -> "AirPollutionAnomaly":
        observed = self.observed_at.astimezone(timezone.utc)
        detected = self.detected_at.astimezone(timezone.utc)
        if detected < observed:
            raise ValueError("detected_at cannot be earlier than observed_at")
        self.observed_at = observed
        self.detected_at = detected
        return self
