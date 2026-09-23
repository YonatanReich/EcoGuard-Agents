"""The shapes used to describe where pollution may drift.

The validators are the safety net: a corridor that claims a source without
evidence, or cites the same evidence twice, is rejected before it can reach a
card and be read as a finding."""

from __future__ import annotations

from datetime import timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from ecoguard.detectors.air_pollution.schemas import (
    ContractModel,
    GeographicCoordinate,
    PollutantUnit,
)


AnalysisOriginKind = Literal[
    "monitoring_location",
    "correlated_source",
    "confirmed_source",
]
WindSourceType = Literal[
    "station_observation",
    "model_forecast",
    "model_reanalysis",
]
ProviderLocationKind = Literal["station", "model_grid"]
ProviderValidity = Literal["valid", "invalid", "unknown"]
TransportDataStatus = Literal["success", "partial", "unavailable"]
TransportSourceQuality = Literal[
    "primary_observation",
    "modeled_fallback",
    "mixed_evidence",
    "unavailable",
]
TransportCorridorMethod = Literal[
    "fixed_angle_screening",
    "direction_variability_screening",
    "model_derived_screening",
]
PotentialDownwindRelevance = Literal[
    "higher",
    "moderate",
    "lower",
    "outside_screening_corridor",
    "indeterminate",
]
SettlementExclusionReason = Literal[
    "outside_transport_corridor",
    "upwind_of_origin",
    "beyond_screening_range",
    "insufficient_wind_evidence",
]
TransportTimeMethod = Literal["constant_wind_kinematic_screening"]

DirectionDegrees = Annotated[float, Field(ge=0, lt=360, strict=True)]
AngularDifferenceDegrees = Annotated[float, Field(ge=0, le=180, strict=True)]
NonNegativeFloat = Annotated[float, Field(ge=0, strict=True)]
SignedFloat = Annotated[float, Field(strict=True)]
RelevanceScore = Annotated[float, Field(ge=0, le=1, strict=True)]
PositiveRank = Annotated[int, Field(ge=1, strict=True)]

_POLLUTANT_ALIASES = {"PM25": "PM2.5", "NOX": "NOx"}
_NON_POLLUTANTS = frozenset(
    {"TEMPERATURE", "HUMIDITY", "PRECIPITATION", "RAIN", "WIND", "WINDSPEED"}
)


def _validated_reference_ids(values: list[str]) -> list[str]:
    """Evidence pointers, rejecting blanks and duplicates."""
    stripped = [value.strip() for value in values]
    if any(not value for value in stripped):
        raise ValueError("evidence reference IDs cannot be blank")
    if len(set(stripped)) != len(stripped):
        raise ValueError("evidence reference IDs must be unique")
    return stripped


class TransportEvidenceReference(ContractModel):
    """Auditable source reference; it carries no derived transport claim."""

    evidence_id: str = Field(min_length=1, max_length=200)
    source_name: str = Field(min_length=1, max_length=300)
    source_type: str | None = Field(default=None, min_length=1, max_length=100)
    reference: str | None = Field(default=None, min_length=1, max_length=1000)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("evidence_id", "source_name", "source_type", "reference")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        """Trim text, treating a blank as absent."""
        return value.strip() if value is not None else None


class AnalysisOrigin(ContractModel):
    """The screening origin, whose kind determines what may be inferred from it."""

    analysis_origin_kind: AnalysisOriginKind
    analysis_origin_coordinates: GeographicCoordinate
    evidence_reference_ids: list[str] = Field(default_factory=list)

    @field_validator("evidence_reference_ids")
    @classmethod
    def validate_reference_ids(cls, values: list[str]) -> list[str]:
        """Reject blank or duplicated evidence pointers."""
        return _validated_reference_ids(values)

    @model_validator(mode="after")
    def source_origins_require_evidence(self):
        """Reject a claimed source that cites no evidence."""
        if (
            self.analysis_origin_kind in {"correlated_source", "confirmed_source"}
            and not self.evidence_reference_ids
        ):
            raise ValueError("source-based origins require supporting evidence references")
        return self


class TransportPollutantObservation(ContractModel):
    """Anomaly measurement with canonical and original provider units separated."""

    pollutant: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z][A-Za-z0-9]*(?:\.[0-9]+)?$",
    )
    concentration: SignedFloat
    normalized_unit: PollutantUnit
    original_value: SignedFloat
    original_unit: str = Field(min_length=1, max_length=100)
    evidence_reference_ids: list[str] = Field(default_factory=list)

    @field_validator("pollutant")
    @classmethod
    def normalize_pollutant(cls, value: str) -> str:
        """One spelling per pollutant, so comparisons work."""
        normalized = _POLLUTANT_ALIASES.get(value.upper(), value)
        if normalized.upper() in _NON_POLLUTANTS:
            raise ValueError("weather context cannot be a pollutant observation")
        return normalized

    @field_validator("original_unit")
    @classmethod
    def strip_original_unit(cls, value: str) -> str:
        """Trim the unit as the provider wrote it."""
        return value.strip()

    @field_validator("evidence_reference_ids")
    @classmethod
    def validate_reference_ids(cls, values: list[str]) -> list[str]:
        """Reject blank or duplicated evidence pointers."""
        return _validated_reference_ids(values)


class PollutionAnomalyTransportEvidence(ContractModel):
    """Detector evidence consumed by transport screening without reclassification."""

    detection_id: str = Field(min_length=1, max_length=200)
    anomaly_observed_at: AwareDatetime
    pollutant_observations: list[TransportPollutantObservation] = Field(min_length=1)
    evidence_references: list[TransportEvidenceReference] = Field(default_factory=list)

    @field_validator("detection_id")
    @classmethod
    def strip_detection_id(cls, value: str) -> str:
        """Trim the detection identifier."""
        return value.strip()

    @field_validator("anomaly_observed_at")
    @classmethod
    def normalize_timestamp(cls, value: AwareDatetime) -> AwareDatetime:
        """Store the time in UTC."""
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def evidence_ids_are_unique(self):
        """Reject a record citing the same evidence twice."""
        identifiers = [item.evidence_id for item in self.evidence_references]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("anomaly evidence IDs must be unique")
        known = set(identifiers)
        for observation in self.pollutant_observations:
            if not set(observation.evidence_reference_ids).issubset(known):
                raise ValueError("pollutant observation references unknown anomaly evidence")
        return self


class WindOriginalUnits(ContractModel):
    """Provider units retained before adapter normalization to canonical units."""

    wind_direction: str = Field(min_length=1, max_length=100)
    wind_speed: str = Field(min_length=1, max_length=100)
    gust_direction: str | None = Field(default=None, min_length=1, max_length=100)
    gust_speed: str | None = Field(default=None, min_length=1, max_length=100)
    direction_stddev: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator(
        "wind_direction",
        "wind_speed",
        "gust_direction",
        "gust_speed",
        "direction_stddev",
    )
    @classmethod
    def strip_units(cls, value: str | None) -> str | None:
        """Trim a unit, treating a blank as absent."""
        return value.strip() if value is not None else None


class WindEvidence(ContractModel):
    """Normalized wind evidence with station/model identity kept explicit."""

    evidence_id: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=300)
    source_type: WindSourceType
    provider_location_kind: ProviderLocationKind
    provider_location_id: str = Field(min_length=1, max_length=200)
    provider_location_name: str | None = Field(default=None, min_length=1, max_length=300)
    requested_coordinates: GeographicCoordinate
    actual_provider_coordinates: GeographicCoordinate
    raw_provider_timestamp: str = Field(min_length=1, max_length=200)
    wind_observed_at: AwareDatetime | None = None
    wind_valid_at: AwareDatetime | None = None
    wind_aggregation_start: AwareDatetime | None = None
    wind_aggregation_end: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    wind_from_direction_deg: DirectionDegrees
    wind_speed_mps: NonNegativeFloat
    gust_from_direction_deg: DirectionDegrees | None = None
    gust_speed_mps: NonNegativeFloat | None = None
    direction_stddev_deg: NonNegativeFloat | None = None
    provider_validity: ProviderValidity
    provider_status: str | None = Field(default=None, min_length=1, max_length=200)
    provider_channel_validity: dict[str, ProviderValidity] = Field(default_factory=dict)
    original_units: WindOriginalUnits
    time_offset_from_anomaly_seconds: SignedFloat
    reference: str | None = Field(default=None, min_length=1, max_length=1000)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator(
        "evidence_id",
        "provider",
        "provider_location_id",
        "provider_location_name",
        "raw_provider_timestamp",
        "provider_status",
        "reference",
    )
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        """Trim text, treating a blank as absent."""
        return value.strip() if value is not None else None

    @field_validator(
        "wind_observed_at",
        "wind_valid_at",
        "wind_aggregation_start",
        "wind_aggregation_end",
        "retrieved_at",
    )
    @classmethod
    def normalize_timestamps(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        """Store times in UTC."""
        return value.astimezone(timezone.utc) if value is not None else None

    @field_validator("provider_channel_validity")
    @classmethod
    def validate_channel_names(cls, values: dict[str, ProviderValidity]):
        """Reject a channel name the provider does not use."""
        if any(not name.strip() for name in values):
            raise ValueError("provider channel names cannot be blank")
        return {name.strip(): value for name, value in values.items()}

    @model_validator(mode="after")
    def validate_source_and_optional_evidence(self):
        """Reject a source claim whose evidence does not support it."""
        if self.source_type == "station_observation":
            if self.provider_location_kind != "station":
                raise ValueError("station observations require a station location")
            if self.wind_observed_at is None or self.wind_valid_at is not None:
                raise ValueError("station observations require wind_observed_at only")
        else:
            if self.provider_location_kind != "model_grid":
                raise ValueError("modeled wind requires a model_grid location")
            if self.wind_valid_at is None or self.wind_observed_at is not None:
                raise ValueError("modeled wind requires wind_valid_at only")

        if (self.wind_aggregation_start is None) != (self.wind_aggregation_end is None):
            raise ValueError("wind aggregation timestamps must be supplied together")
        if (
            self.wind_aggregation_start is not None
            and self.wind_aggregation_end is not None
            and self.wind_aggregation_end < self.wind_aggregation_start
        ):
            raise ValueError("wind aggregation end cannot precede its start")

        optional_units = (
            (self.gust_from_direction_deg, self.original_units.gust_direction),
            (self.gust_speed_mps, self.original_units.gust_speed),
            (self.direction_stddev_deg, self.original_units.direction_stddev),
        )
        if any((value is None) != (unit is None) for value, unit in optional_units):
            raise ValueError("optional wind values and their original units must match")
        return self

    @property
    def effective_at(self) -> AwareDatetime:
        """The time this reading actually describes."""
        value = self.wind_observed_at if self.source_type == "station_observation" else self.wind_valid_at
        assert value is not None
        return value


class SettlementTransportCandidate(ContractModel):
    """One settlement candidate supplied by spatial context, before ranking."""

    settlement_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    coordinates: GeographicCoordinate
    source_provider: str | None = Field(default=None, min_length=1, max_length=300)
    source_feature_id: str | None = Field(default=None, min_length=1, max_length=200)
    original_source_distance_m: NonNegativeFloat | None = None

    @field_validator("settlement_id", "name", "source_provider", "source_feature_id")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        """Trim text, treating a blank as absent."""
        return value.strip() if value is not None else None


class PollutionTransportPredictionInput(ContractModel):
    """Coordinator-routed evidence for an independently invoked screening step."""

    prediction_id: str = Field(min_length=1, max_length=200)
    incident_id: str | None = Field(default=None, min_length=1, max_length=200)
    coordinator_routing_id: str | None = Field(default=None, min_length=1, max_length=200)
    analysis_purpose: Literal["transport_screening"] = "transport_screening"
    analysis_origin: AnalysisOrigin
    anomaly_evidence: PollutionAnomalyTransportEvidence
    wind_evidence: WindEvidence
    settlement_candidates: list[SettlementTransportCandidate] = Field(default_factory=list)
    exposure_not_confirmed: Literal[True] = True

    @field_validator("prediction_id", "incident_id", "coordinator_routing_id")
    @classmethod
    def strip_identity(cls, value: str | None) -> str | None:
        """Trim the identifier."""
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_routing_and_evidence_alignment(self):
        """Reject a request whose wind evidence does not match the reading it is for."""
        if self.incident_id is None and self.coordinator_routing_id is None:
            raise ValueError("incident_id or coordinator_routing_id is required")
        if (
            self.wind_evidence.requested_coordinates
            != self.analysis_origin.analysis_origin_coordinates
        ):
            raise ValueError("wind requested coordinates must match the analysis origin")
        expected_offset = (
            self.wind_evidence.effective_at - self.anomaly_evidence.anomaly_observed_at
        ).total_seconds()
        if abs(expected_offset - self.wind_evidence.time_offset_from_anomaly_seconds) > 1e-6:
            raise ValueError("wind time offset does not match evidence timestamps")
        identifiers = [item.settlement_id for item in self.settlement_candidates]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("settlement candidate IDs must be unique")
        return self


class DerivedTransportScreening(ContractModel):
    """Overall derived screening metadata, separate from provider evidence."""

    result_kind: Literal["estimated_transport_corridor"] = "estimated_transport_corridor"
    downwind_to_direction_deg: DirectionDegrees | None = None
    corridor_method: TransportCorridorMethod | None = None
    corridor_half_angle_deg: Annotated[float, Field(gt=0, le=180, strict=True)] | None = None
    algorithm_version: str = Field(min_length=1, max_length=200)
    parameter_version: str = Field(min_length=1, max_length=200)
    data_status: TransportDataStatus
    source_quality: TransportSourceQuality
    generated_at: AwareDatetime
    limitations: list[str] = Field(min_length=1)
    evidence_reference_ids: list[str] = Field(min_length=1)
    exposure_not_confirmed: Literal[True] = True

    @field_validator("algorithm_version", "parameter_version")
    @classmethod
    def strip_version(cls, value: str) -> str:
        """Trim the version label."""
        return value.strip()

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: AwareDatetime) -> AwareDatetime:
        """Store the time in UTC."""
        return value.astimezone(timezone.utc)

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, values: list[str]) -> list[str]:
        """Reject a blank caveat, since an empty one says nothing."""
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("limitations cannot contain blank entries")
        return stripped

    @field_validator("evidence_reference_ids")
    @classmethod
    def validate_reference_ids(cls, values: list[str]) -> list[str]:
        """Reject blank or duplicated evidence pointers."""
        return _validated_reference_ids(values)

    @model_validator(mode="after")
    def status_is_coherent(self):
        """Reject a screening whose status contradicts its contents."""
        derived = (
            self.downwind_to_direction_deg,
            self.corridor_method,
            self.corridor_half_angle_deg,
        )
        if self.data_status == "unavailable":
            if any(value is not None for value in derived) or self.source_quality != "unavailable":
                raise ValueError("unavailable screening cannot contain derived corridor values")
        elif any(value is None for value in derived) or self.source_quality == "unavailable":
            raise ValueError("available screening requires complete derived corridor metadata")
        return self


class SettlementTransportRelevanceResult(ContractModel):
    """Geometry and heuristic relevance; relevance_score is not a probability."""

    settlement_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    coordinates: GeographicCoordinate
    geodesic_distance_m: NonNegativeFloat
    bearing_from_origin_deg: DirectionDegrees
    angular_difference_deg: AngularDifferenceDegrees
    along_wind_distance_m: SignedFloat
    crosswind_distance_m: NonNegativeFloat
    inside_transport_corridor: bool
    relevance_score: RelevanceScore
    score_components: dict[str, SignedFloat] = Field(default_factory=dict)
    rank: PositiveRank | None = None
    exclusion_reason: SettlementExclusionReason | None = None
    potential_downwind_relevance: PotentialDownwindRelevance
    kinematic_advection_time_seconds: NonNegativeFloat | None = None
    transport_time_method: TransportTimeMethod | None = None
    transport_time_assumptions: list[str] = Field(default_factory=list)

    @field_validator("settlement_id", "name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        """Trim text, treating a blank as absent."""
        return value.strip()

    @field_validator("score_components")
    @classmethod
    def validate_score_components(cls, values: dict[str, float]):
        """Reject a score whose parts do not add up."""
        if any(not name.strip() for name in values):
            raise ValueError("score component names cannot be blank")
        return {name.strip(): value for name, value in values.items()}

    @field_validator("transport_time_assumptions")
    @classmethod
    def validate_time_assumptions(cls, values: list[str]) -> list[str]:
        """Reject travel-time assumptions that are not stated."""
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("transport-time assumptions cannot contain blank entries")
        return stripped

    @model_validator(mode="after")
    def result_is_coherent(self):
        """Reject a result whose parts contradict each other."""
        if self.exclusion_reason is None and self.rank is None:
            raise ValueError("non-excluded settlement results require a rank")
        if self.exclusion_reason is not None and self.rank is not None:
            raise ValueError("excluded settlement results cannot have a rank")
        if self.exclusion_reason == "outside_transport_corridor":
            if self.inside_transport_corridor or self.potential_downwind_relevance != "outside_screening_corridor":
                raise ValueError("outside-corridor exclusion must remain screening-only")

        has_estimate = self.kinematic_advection_time_seconds is not None
        if has_estimate:
            if self.transport_time_method is None or not self.transport_time_assumptions:
                raise ValueError("kinematic estimate requires a method and assumptions")
        elif self.transport_time_method is not None or self.transport_time_assumptions:
            raise ValueError("transport-time metadata requires a kinematic estimate")
        return self


class PollutionTransportPredictionResult(ContractModel):
    """Transport-screening output; never exposure, response or allocation."""

    prediction_id: str = Field(min_length=1, max_length=200)
    incident_id: str | None = Field(default=None, min_length=1, max_length=200)
    coordinator_routing_id: str | None = Field(default=None, min_length=1, max_length=200)
    detection_id: str = Field(min_length=1, max_length=200)
    analysis_origin: AnalysisOrigin
    transport_screening: DerivedTransportScreening
    settlement_results: list[SettlementTransportRelevanceResult] = Field(default_factory=list)
    exposure_not_confirmed: Literal[True] = True

    @field_validator("prediction_id", "incident_id", "coordinator_routing_id", "detection_id")
    @classmethod
    def strip_identity(cls, value: str | None) -> str | None:
        """Trim the identifier."""
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_result_collection(self):
        """Reject a result set that is internally inconsistent."""
        if self.incident_id is None and self.coordinator_routing_id is None:
            raise ValueError("incident_id or coordinator_routing_id is required")
        if self.transport_screening.data_status == "unavailable" and self.settlement_results:
            raise ValueError("unavailable screening cannot contain settlement results")
        identifiers = [item.settlement_id for item in self.settlement_results]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("settlement result IDs must be unique")
        ranks = [item.rank for item in self.settlement_results if item.rank is not None]
        if len(set(ranks)) != len(ranks):
            raise ValueError("settlement ranks must be unique")
        return self
