"""Storage-independent schemas for exact air-pollution baseline lookup."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ecoguard.shared.air_quality_schemas import GeographicCoordinate


class LookupContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BaselineIdentity(LookupContract):
    provider: str = Field(min_length=1, max_length=200)
    station_id: str = Field(min_length=1, max_length=100)
    channel_id: str = Field(min_length=1, max_length=100)
    pollutant: str = Field(min_length=1, max_length=32)
    canonical_unit: str = Field(min_length=1, max_length=100)
    baseline_family: Literal["completed_hour", "five_minute_observation"]


class BaselineLookupRequest(LookupContract):
    """One exact identity/time request in an ordered batch lookup."""

    identity: BaselineIdentity
    month: int = Field(ge=1, le=12)
    hour: int = Field(ge=0, le=23)
    baseline_version_id: int | None = Field(default=None, gt=0)


class BaselineBucketStatistics(LookupContract):
    status: Literal["ok", "insufficient_history"]
    sample_count: int = Field(ge=0)
    distinct_days: int = Field(ge=0)
    distinct_years: int = Field(ge=0)
    years_present: list[int]
    mean: float | None = None
    median: float | None = None
    std: float | None = Field(default=None, ge=0)
    mad: float | None = Field(default=None, ge=0)
    p05: float | None = None
    p25: float | None = None
    p75: float | None = None
    p95: float | None = None


class BaselineVersionProvenance(LookupContract):
    baseline_version_id: int
    parent_version_id: int | None = None
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_status: Literal["FULL_BASELINE", "PARTIAL_BASELINE", "INSUFFICIENT_HISTORY"]
    lifecycle_status: Literal["draft", "active", "superseded"]
    schema_version: str
    method_version: str | None = None
    source_name: str
    source_version: str | None = None
    training_start: date
    training_end: date
    imported_at: datetime
    generated_at: datetime | None = None
    aggregation_policy_version: str
    quality_policy_version: str
    source_metadata: dict[str, Any]
    aggregation_metadata: dict[str, Any]
    quality_metadata: dict[str, Any]
    coverage_metadata: dict[str, Any]


LookupStatus = Literal[
    "available", "insufficient_history", "profile_unavailable",
    "baseline_unavailable", "bucket_unavailable", "invalid_identity",
]


class BaselineLookupResult(LookupContract):
    status: LookupStatus
    reason: str
    mode: Literal["operational", "draft_validation"]
    identity: BaselineIdentity | None
    month: int | None = Field(default=None, ge=1, le=12)
    hour: int | None = Field(default=None, ge=0, le=23)
    station_name: str | None = None
    catalog_status: str | None = None
    catalog_reason: str | None = None
    version: BaselineVersionProvenance | None = None
    bucket: BaselineBucketStatistics | None = None


class LiveObservationContext(LookupContract):
    provider: str
    station_id: str
    channel_id: str
    pollutant: str
    value: float
    observed_at: AwareDatetime
    provider_timestamp: str
    measurement_unit: str
    unit_source: Literal["reading"]
    reading_unit: str
    location: GeographicCoordinate


LiveBaselineContextStatus = Literal[
    "available", "insufficient_history", "profile_unavailable",
    "baseline_unavailable", "bucket_unavailable", "invalid_live_observation",
]


class LiveBaselineContextResult(LookupContract):
    status: LiveBaselineContextStatus
    reason: str
    mode: Literal["operational", "draft_validation"]
    live_observation: LiveObservationContext | None = None
    station_name: str | None = None
    lookup_identity: BaselineIdentity | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    hour: int | None = Field(default=None, ge=0, le=23)
    lookup_status: LookupStatus | None = None
    baseline_statistics: BaselineBucketStatistics | None = None
    baseline_version: BaselineVersionProvenance | None = None
    comparison_eligible: bool = False
    eligibility_reason: str
