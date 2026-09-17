"""Backend mirror of the frontend SharedEvent delivery contract."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any, Literal, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class EventContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class EventProcessingMetadata(EventContract):
    route: str
    status: str
    failure_stage: str | None = None
    failure_reason: str | None = None
    retryable: bool = False
    attempt_count: int = Field(ge=1)
    last_attempt_at: AwareDatetime
    processed_at: AwareDatetime
    using_last_successful_payload: bool = False


class ProtocolCitation(EventContract):
    chunk_id: str
    document_id: str
    document_title: str
    source_url: str | None = None
    heading_path: str
    quoted_text: str
    supports: str
    verified: bool


class FireResponseAction(EventContract):
    action: str
    responsible_unit: str
    timeframe: Literal["immediate", "within_1_hour", "within_6_hours", "ongoing"]


class FireDetails(EventContract):
    detection_confidence: str | None = None
    fire_weather_severity: str | None = None
    risk_score: float | None = None
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    confidence: Literal["low", "medium", "high"] | None = None
    primary_drivers: list[str] = Field(default_factory=list)
    explanation: str | None = None
    evidence_gaps: list[str] = Field(default_factory=list)
    recommended_units: list[str] = Field(default_factory=list)
    response_plan: list[str] = Field(default_factory=list)
    response_actions: list[FireResponseAction] = Field(default_factory=list)
    protocol_citations: list[ProtocolCitation] = Field(default_factory=list)


class AirPollutionBaselineContext(EventContract):
    p95: float
    month: int | None = None
    hour: int | None = None
    sample_count: int | None = None
    distinct_days: int | None = None
    distinct_years: int | None = None
    baseline_family: str | None = None
    baseline_version_id: int | str | None = None
    baseline_content_sha256: str | None = None


class MinistryAirQualityIndex(EventContract):
    station_id: str | None = None
    pollutant: str | None = None
    resolved_channel_id: str | None = None
    station_index: float
    station_category: str
    category_color: str | None = None
    pollutant_sub_index: float | None = None
    driving_pollutant: str | None = None
    averaged_concentration: float | None = None
    averaging_period_minutes: int | None = None
    provider_timestamp: AwareDatetime
    preliminary: bool | None = None
    source: str | None = None


class OfficialPollutantClassification(EventContract):
    classification: Literal["GOOD", "MODERATE", "LOW", "VERY_LOW", "UNKNOWN"]
    pollutant: str
    pollutant_sub_index: float | None = None
    source: str
    reason: str


class AirPollutionPublicationPolicy(EventContract):
    publish_to_operational_dashboard: bool
    emphasis: Literal["none", "standard", "strong"]
    reason: str


class PossibleSourceCorrelation(EventContract):
    kind: Literal["possible_source_correlation"]
    source_hazard: Literal["fire"]
    source_incident_id: str
    distance_km: float | None = None
    bearing_deg: float | None = None
    lag_hours: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    statement: str


class AirPollutionAdditionalVerification(EventContract):
    status: Literal[
        "CORROBORATED",
        "NO_EXTERNAL_EVIDENCE",
        "VERIFICATION_UNAVAILABLE",
        "CONTEXT_ONLY",
    ]
    checked_at: AwareDatetime
    providers_checked: list[str] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)
    reason: str
    limitations: list[str] = Field(default_factory=list)
    possible_source_correlations: list[PossibleSourceCorrelation] = Field(
        default_factory=list
    )


class AirPollutionWindEvidence(EventContract):
    provider: str
    source_type: Literal[
        "station_observation", "model_forecast", "model_reanalysis"
    ]
    provider_location_name: str | None = None
    observed_or_valid_at: AwareDatetime
    wind_from_direction_deg: float
    wind_speed_mps: float
    gust_from_direction_deg: float | None = None
    gust_speed_mps: float | None = None
    direction_stddev_deg: float | None = None
    reference: str | None = None
    evidence_id: str | None = None


class GeoJsonPolygon(EventContract):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


class GeoJsonLineString(EventContract):
    type: Literal["LineString"] = "LineString"
    coordinates: list[list[float]]


class TransportTimeEvidence(EventContract):
    status: Literal["estimated", "suppressed", "unavailable"]
    seconds: float | None = None
    method: Literal["constant_wind_kinematic_screening"] | None = None
    assumptions: list[str] = Field(default_factory=list)
    unavailable_reason: str | None = None


class AirPollutionSettlement(EventContract):
    id: str
    name: str
    longitude: float
    latitude: float
    inside_transport_corridor: bool
    rank: int | None = None
    potential_downwind_relevance: str
    distance_m: float | None = None
    transport_time: TransportTimeEvidence | None = None


class AirPollutionTransportScreening(EventContract):
    corridor: GeoJsonPolygon | None = None
    centerline: GeoJsonLineString | None = None
    downwind_to_direction_deg: float | None = None
    corridor_method: str | None = None
    corridor_half_angle_deg: float | None = None
    max_screening_distance_m: float | None = None
    direction_stddev_deg: float | None = None
    geometry_reference: str | None = None


class CorridorPopulationContext(EventContract):
    total_relevant_population: int
    intersected_cell_count: int
    queried_at: AwareDatetime
    geometry_reference: str
    dataset_reference_year: int | None = None


class AirPollutionRecommendation(EventContract):
    recommendation: str
    rationale: str
    responsible_authority_type: str
    resource_type: str
    timeframe: Literal[
        "immediate", "within_1_hour", "within_6_hours", "ongoing", "not_specified"
    ]
    priority: Literal["urgent", "high", "routine", "monitoring", "not_specified"]
    spatial_relevance: str | None = None


class VerifiedReference(EventContract):
    id: str
    document_title: str
    source_url: str | None = None
    quoted_text: str
    supports: str
    verified: Literal[True] = True


class ComponentUnavailableReason(EventContract):
    component: str
    reason: str


class AirPollutionStation(EventContract):
    id: str
    name: str | None = None
    provider: str | None = None
    channel_id: str | None = None


class AirPollutionDetails(EventContract):
    pollutant: str
    station: AirPollutionStation
    measured_value: float
    unit: str
    observation_timestamp: AwareDatetime
    historical_baseline: AirPollutionBaselineContext | None = None
    ministry_aqi: MinistryAirQualityIndex | None = None
    official_pollutant_classification: OfficialPollutantClassification | None = None
    publication_policy: AirPollutionPublicationPolicy | None = None
    additional_verification: AirPollutionAdditionalVerification | None = None
    wind: AirPollutionWindEvidence | None = None
    transport: AirPollutionTransportScreening | None = None
    relevant_settlements: list[AirPollutionSettlement] = Field(default_factory=list)
    population_within_screening_corridor: CorridorPopulationContext | None = None
    recommendations: list[AirPollutionRecommendation] = Field(default_factory=list)
    verified_references: list[VerifiedReference] = Field(default_factory=list)
    unavailable_components: list[ComponentUnavailableReason] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    trend: Literal["RISING", "STABLE", "FALLING"] | None = None

    @model_validator(mode="after")
    def _ministry_index_matches_projected_anomaly(self):
        index = self.ministry_aqi
        if index is None:
            return self
        identity = (
            index.station_id,
            index.pollutant,
            index.resolved_channel_id,
        )
        if identity == (None, None, None):
            # Backward-compatible read of projections written before explicit
            # Ministry identity was preserved. Such rows cannot qualify Path B.
            return self
        if any(value is None for value in identity):
            raise ValueError("Ministry AQI identity must be complete")
        if identity != (self.station.id, self.pollutant, self.station.channel_id):
            raise ValueError("Ministry AQI identity must match the projected anomaly")
        window_start = index.provider_timestamp - timedelta(
            minutes=index.averaging_period_minutes
        )
        if not window_start < self.observation_timestamp <= index.provider_timestamp:
            raise ValueError("projected anomaly is outside the Ministry AQI window")
        return self


class CommonSharedEvent(EventContract):
    id: str
    title: str
    description: str
    latitude: float
    longitude: float
    observed_at: AwareDatetime | None = None
    classification: Literal["emergency", "advisory"]
    analysis_status: Literal[
        "success", "partial", "unavailable", "failed", "skipped"
    ]
    planning_status: Literal[
        "success", "partial", "unavailable", "failed", "skipped"
    ]
    processing: EventProcessingMetadata | None = None


class AirPollutionSharedEvent(CommonSharedEvent):
    type: Literal["air_pollution"] = "air_pollution"
    classification: Literal["advisory"] = "advisory"
    details: AirPollutionDetails


class FireSharedEvent(CommonSharedEvent):
    type: Literal["fire"] = "fire"
    details: FireDetails


class GenericSharedEvent(CommonSharedEvent):
    type: Literal["flood", "other"]
    details: dict[str, Any]


SharedEvent = Annotated[
    Union[AirPollutionSharedEvent, FireSharedEvent, GenericSharedEvent],
    Field(discriminator="type"),
]


class SharedEventFeed(EventContract):
    events: list[SharedEvent] = Field(default_factory=list)
