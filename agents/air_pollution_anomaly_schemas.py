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

PollutantUnit = Literal["µg/m³", "mg/m³", "ppb", "ppm"]
AnomalySeverity = Literal["low", "medium", "high", "critical"]

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
    observed_at: AwareDatetime | None = None
    source_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("pollutant")
    @classmethod
    def _normalize_pollutant(cls, value: str) -> str:
        normalized = _POLLUTANT_ALIASES.get(value.upper(), value)
        if normalized.upper() in _NON_POLLUTANT_CONTEXT_IDS:
            raise ValueError("weather context cannot be a pollutant observation")
        return normalized

    @field_validator("provider_pollutant_id", "source_id")
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
