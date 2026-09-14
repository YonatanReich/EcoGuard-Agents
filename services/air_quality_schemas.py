"""Storage-independent schemas for collected air-quality data.

These records sit between a provider adapter and the future shared repository.
They are observations, not anomaly detections or incident decisions.
"""

from __future__ import annotations

from datetime import timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

LIVE_QUALITY_POLICY = "ecoguard-provider-valid-signed-v1"

PollutantUnit = Literal["µg/m³", "mg/m³", "ng/m³", "ppb", "ppm"]
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
    """Strict base for source measurement records."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GeographicCoordinate(ContractModel):
    """Provider-independent WGS84 point."""

    latitude: float = Field(ge=-90, le=90, strict=True)
    longitude: float = Field(ge=-180, le=180, strict=True)


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



MINISTRY_PROVIDER_ID = "israel_ministry_environment_air_monitoring"


class AirQualityMonitor(ContractModel):
    """One pollutant monitor/channel advertised by a station."""

    provider_channel_id: str = Field(min_length=1, max_length=100)
    pollutant: str = Field(min_length=1, max_length=32)
    provider_pollutant_id: str | None = Field(default=None, max_length=100)
    unit: PollutantUnit
    provider_unit: str = Field(min_length=1, max_length=100)
    active: bool | None = None
    provider_state: str | None = Field(default=None, max_length=100)
    percent_valid_required: float | None = Field(default=None, ge=0, le=100)


class AirQualityStation(ContractModel):
    """Normalized station metadata suitable for later persistence."""

    provider: Literal[MINISTRY_PROVIDER_ID] = MINISTRY_PROVIDER_ID
    provider_station_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    location: GeographicCoordinate
    short_name: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=300)
    address: str | None = Field(default=None, max_length=500)
    provider_region_id: str | None = Field(default=None, max_length=100)
    owner: str | None = Field(default=None, max_length=300)
    active: bool | None = None
    monitors: list[AirQualityMonitor] = Field(default_factory=list)


class AirQualityObservation(PollutantObservation):
    """A valid, normalized, preliminary Ministry concentration reading."""

    provider: Literal[MINISTRY_PROVIDER_ID] = MINISTRY_PROVIDER_ID
    # Override the generic nonnegative contract only for provider observations.
    value: float = Field(strict=True)
    unit: PollutantUnit | None = None
    measurement_unit: PollutantUnit | None = None
    unit_source: Literal["reading", "metadata_fallback", "unknown"] = "unknown"
    metadata_unit: str | None = Field(default=None, max_length=100)
    reading_unit: str | None = Field(default=None, max_length=100)
    # Missing provenance on legacy records must not be upgraded implicitly.
    quality_policy: Literal["ecoguard-provider-valid-signed-v1"] | None = None
    provider_station_id: str = Field(min_length=1, max_length=100)
    provider_channel_id: str = Field(min_length=1, max_length=100)
    location: GeographicCoordinate
    observed_at: AwareDatetime
    provider_timestamp: str = Field(min_length=1, max_length=100)
    valid: Literal[True] = True
    provider_status_id: str | None = Field(default=None, max_length=100)
    provider_status: str | None = Field(default=None, max_length=100)
    quality_control: Literal["preliminary_unvalidated"] = "preliminary_unvalidated"

    @model_validator(mode="after")
    def _provenance(self):
        if self.value == -9999:
            raise ValueError("provider sentinel is not a measurement")
        if self.unit_source == "reading":
            if not self.reading_unit or self.measurement_unit is None or self.unit != self.measurement_unit:
                raise ValueError("reading unit provenance is incomplete")
        elif self.measurement_unit is not None:
            raise ValueError("metadata cannot establish measurement unit")
        if self.unit_source == "metadata_fallback" and (not self.metadata_unit or self.unit is None):
            raise ValueError("metadata fallback is incomplete")
        return self

    @field_validator("observed_at")
    @classmethod
    def _to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(timezone.utc)


ExclusionReason = Literal[
    "invalid_sentinel",
    "provider_marked_invalid",
    "inactive_station",
    "inactive_channel",
    "unusable_provider_status",
    "unsupported_pollutant",
    "unsupported_unit",
    "invalid_value",
    "malformed_timestamp",
    "station_metadata_missing",
    "invalid_station_metadata",
    "malformed_channel",
]


class ExcludedAirQualityReading(ContractModel):
    """Sanitized provenance explaining why a provider channel was excluded."""

    provider: Literal[MINISTRY_PROVIDER_ID] = MINISTRY_PROVIDER_ID
    reason: ExclusionReason
    provider_station_id: str | None = Field(default=None, max_length=100)
    provider_channel_id: str | None = Field(default=None, max_length=100)
    provider_pollutant: str | None = Field(default=None, max_length=100)
    provider_pollutant_id: str | None = Field(default=None, max_length=100)
    provider_unit: str | None = Field(default=None, max_length=100)
    provider_timestamp: str | None = Field(default=None, max_length=100)
    provider_status_id: str | None = Field(default=None, max_length=100)
    provider_status: str | None = Field(default=None, max_length=100)


CollectionStatus = Literal["success", "partial", "failed"]


class StationCollectionResult(ContractModel):
    status: CollectionStatus
    stations: list[AirQualityStation] = Field(default_factory=list)
    excluded_count: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)


class AirQualityCollectionResult(ContractModel):
    """One collection run with clean observations and exclusion accounting."""

    provider: Literal[MINISTRY_PROVIDER_ID] = MINISTRY_PROVIDER_ID
    status: CollectionStatus
    collected_at: AwareDatetime
    observations: list[AirQualityObservation] = Field(default_factory=list)
    excluded: list[ExcludedAirQualityReading] = Field(default_factory=list)
    stations_considered: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)

    @field_validator("collected_at")
    @classmethod
    def _collection_time_to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(timezone.utc)


class MinistryAirQualityIndexEvidence(ContractModel):
    """Source-native Ministry index evidence; never an EcoGuard severity label."""

    source: Literal["Israeli Ministry of Environmental Protection"] = (
        "Israeli Ministry of Environmental Protection"
    )
    provider: Literal[MINISTRY_PROVIDER_ID] = MINISTRY_PROVIDER_ID
    classification_system: Literal["ministry_air_quality_index"] = (
        "ministry_air_quality_index"
    )
    station_id: str = Field(min_length=1, max_length=100)
    station_index: float
    station_category: str = Field(min_length=1, max_length=300)
    category_color: str | None = Field(default=None, max_length=100)
    driving_pollutant: str = Field(min_length=1, max_length=32)
    pollutant: str = Field(min_length=1, max_length=32)
    pollutant_sub_index: float
    monitor_id: str = Field(min_length=1, max_length=100)
    resolved_channel_id: str = Field(min_length=1, max_length=100)
    averaged_concentration: float
    canonical_unit: PollutantUnit | None = None
    provider_unit: str | None = Field(default=None, min_length=1, max_length=100)
    unit_source: Literal["station_metadata", "unknown"] = "unknown"
    averaging_period_minutes: int = Field(gt=0)
    provider_timestamp: AwareDatetime
    raw_provider_timestamp: str = Field(min_length=1, max_length=100)
    source_endpoint: Literal["stations/{station_id}/indexFastSrv"] = (
        "stations/{station_id}/indexFastSrv"
    )
    evidence_id: str = Field(min_length=1, max_length=300)
    retrieved_at: AwareDatetime
    preliminary: Literal[True] = True
    limitations: list[str] = Field(min_length=1)

    @field_validator("provider_timestamp", "retrieved_at")
    @classmethod
    def _index_times_to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _index_identity_and_unit(self):
        if self.monitor_id != self.resolved_channel_id:
            raise ValueError("MonitorId must resolve exactly to channel_id")
        if self.unit_source == "station_metadata":
            if self.canonical_unit is None or self.provider_unit is None:
                raise ValueError("station metadata unit provenance is incomplete")
        elif self.canonical_unit is not None or self.provider_unit is not None:
            raise ValueError("unknown unit provenance cannot carry a unit")
        return self


class MinistryAirQualityIndexLookupResult(ContractModel):
    """Fail-closed result of matching one event to source-native index evidence."""

    status: Literal["available", "unavailable"]
    evidence: MinistryAirQualityIndexEvidence | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _coherent_result(self):
        if self.status == "available":
            if self.evidence is None or self.reason is not None:
                raise ValueError("available index lookup requires evidence only")
        elif self.evidence is not None or self.reason is None:
            raise ValueError("unavailable index lookup requires a reason only")
        return self
