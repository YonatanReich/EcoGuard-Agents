"""Storage-independent schemas for collected air-quality data.

These records sit between a provider adapter and the future shared repository.
They are observations, not anomaly detections or incident decisions.
"""

from __future__ import annotations

from datetime import timezone
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator

from agents.air_pollution_anomaly_schemas import (
    ContractModel,
    GeographicCoordinate,
    PollutantObservation,
    PollutantUnit,
)

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
    provider_station_id: str = Field(min_length=1, max_length=100)
    provider_channel_id: str = Field(min_length=1, max_length=100)
    location: GeographicCoordinate
    observed_at: AwareDatetime
    provider_timestamp: str = Field(min_length=1, max_length=100)
    valid: Literal[True] = True
    provider_status_id: str | None = Field(default=None, max_length=100)
    provider_status: str | None = Field(default=None, max_length=100)
    quality_control: Literal["preliminary_unvalidated"] = "preliminary_unvalidated"

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
