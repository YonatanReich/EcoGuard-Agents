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


class AllocationRequirement(EventContract):
    requested: int = Field(ge=0)
    assigned: int = Field(ge=0)
    shortfall: int = Field(ge=0)


class AllocationRouteGeometry(EventContract):
    type: Literal["LineString"] = "LineString"
    coordinates: list[list[float]]


class AllocationRoute(EventContract):
    status: str
    provider: str
    profile: str
    distance_m: float | None = Field(default=None, ge=0)
    duration_s: float | None = Field(default=None, ge=0)
    geometry: AllocationRouteGeometry | None = None
    origin: dict[str, Any] | None = None
    destination: dict[str, Any] | None = None
    estimated_arrival_at: AwareDatetime | None = None
    road_access_verified: bool
    requires_field_access_confirmation: bool
    offroad_segment: dict[str, Any] | None = None
    steps_he: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class AllocatedStation(EventContract):
    database_id: int = Field(gt=0)
    name: str
    address: str | None = None
    unit_type: str
    recommended_unit: str
    latitude: float
    longitude: float
    distance_km: float | None = Field(default=None, ge=0)
    allocation_status: str
    selection_reason: str
    route: AllocationRoute | None = None


class AllocationSettlement(EventContract):
    population: int | None = Field(default=None, ge=0)
    households: int | None = Field(default=None, ge=0)
    authority: str | None = None
    authority_type: str | None = None
    authority_phone: str | None = None
    authority_address: str | None = None
    authority_website: str | None = None
    area_km2: float | None = Field(default=None, ge=0)


class ResourceAllocationSummary(EventContract):
    status: str
    routing_status: str
    requirements: dict[str, AllocationRequirement] = Field(default_factory=dict)
    shortages: dict[str, int] = Field(default_factory=dict)
    stations: list[AllocatedStation] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    settlement: AllocationSettlement | None = None


class EarthquakeResourceAllocationSummary(ResourceAllocationSummary):
    unsupported_units: list[str] = Field(default_factory=list)
    allocation_policy: Literal["earthquake_minimum_response_v1"]
    allocation_basis: Literal["protocol_recommended_units"]
    quantity_source: Literal["ecoguard_minimum_response_policy"]


class FireSpreadRing(EventContract):
    """One forecast extent, as the analyser draws it."""

    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


class FireSpread(EventContract):
    """Where the fire is forecast to go, and how fast.

    Two rings rather than one: `likely` on the forecast wind, `possible` as the
    union of a wind-error ensemble. A map that draws only the first understates
    the question an operator is actually asking.
    """

    likely: FireSpreadRing | None = None
    possible: FireSpreadRing | None = None
    heading_deg: float | None = None
    heading_compass: str | None = None
    head_rate_m_per_min: float | None = None
    head_distance_m: float | None = None
    horizon_minutes: float | None = None


class FireExposedSettlement(EventContract):
    """A settlement the fire is in, or forecast to reach."""

    name: str
    name_he: str | None = None
    population: int | None = None
    exposure: Literal["burning", "likely", "possible"]
    arrival_minutes: float | None = None
    distance_m: float | None = None
    authority_phone: str | None = None
    fire_district: str | None = None
    police_station: str | None = None


class FireEvacuationDirective(EventContract):
    """Which settlement moves, when, and who holds the decision."""

    name: str
    priority: Literal["immediate", "prepare", "standby"]
    population: int | None = None
    reason: str
    arrival_minutes: float | None = None
    authority: str | None = None
    authority_phone: str | None = None
    police_station: str | None = None


class FireSiteAtRisk(EventContract):
    """Something in the path that is not a settlement."""

    name: str
    kind: str
    category: Literal["hazard", "life_safety", "economic"]
    exposure: Literal["burning", "likely", "possible"]
    distance_m: float | None = None


class FireDetectionVerdict(EventContract):
    """Whether this is a fire at all, and on what evidence."""

    verdict: Literal["confirmed", "probable", "possible", "doubtful", "unassessed"]
    score: int | None = None
    reasons: list[dict[str, Any]] = Field(default_factory=list)


class FireDispatchStation(EventContract):
    """One responsible station, and under which request type."""

    name: str
    district: str | None = None
    teams: int | None = None
    role: str
    request_type: str


class FireDispatch(EventContract):
    """Who is responsible: the grade, the stations, the police and MDA.

    Computed rather than generated, which is why it sits beside the plan
    instead of inside it. `teams_shortfall` is carried explicitly because a
    dispatch that could not be filled must not look like one that was.
    """

    grade: int | None = None
    grade_reason: str | None = None
    teams_required: int | None = None
    teams_assigned: int | None = None
    teams_shortfall: int | None = None
    home_district: str | None = None
    stations: list[FireDispatchStation] = Field(default_factory=list)
    police: list[dict[str, Any]] = Field(default_factory=list)
    mda: list[dict[str, Any]] = Field(default_factory=list)
    is_national_event: bool = False
    national_event_basis: str | None = None
    limits: list[str] = Field(default_factory=list)


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
    resource_allocation: ResourceAllocationSummary | None = None

    # The analyser's measured findings and the planner's computed dispatch,
    # carried beside the narrative rather than folded into it. Every one of
    # these is None or empty when the corresponding step did not run, which a
    # reader must be able to tell from a step that ran and found nothing.
    detection: FireDetectionVerdict | None = None
    spread: FireSpread | None = None
    exposed_settlements: list[FireExposedSettlement] = Field(default_factory=list)
    sites_at_risk: list[FireSiteAtRisk] = Field(default_factory=list)
    evacuation: list[FireEvacuationDirective] = Field(default_factory=list)
    people_in_spread: int | None = None
    population_at_risk: dict[str, int] = Field(default_factory=dict)
    dispatch: FireDispatch | None = None
    incident_report: str | None = None
    coverage_gaps: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)


class EarthquakeTown(EventContract):
    town_id: str
    name_he: str
    name_en: str
    cbs_code: str | None = None


class EarthquakePopulationSummary(EventContract):
    status: Literal["available", "unavailable"]
    wording: Literal[
        "Estimated population geographically located within the impact area"
    ] = "Estimated population geographically located within the impact area"
    estimated_population: int | None = Field(default=None, ge=0)
    intersected_cell_count: int | None = Field(default=None, ge=0)
    reason: str | None = None


class EarthquakeDetails(EventContract):
    provider_event_id: str
    magnitude: float
    depth_km: float = Field(ge=0)
    estimated_impact_radius_km: float = Field(gt=0)
    estimated_impact_area: "GeoJsonPolygon"
    towns: list[EarthquakeTown] = Field(default_factory=list)
    towns_status: Literal["available", "unavailable"]
    population_summary: EarthquakePopulationSummary
    provider: Literal["GSI"] = "GSI"
    source: str
    plan_summary: str | None = None
    recommended_units: list[str] = Field(default_factory=list)
    response_actions: list[FireResponseAction] = Field(default_factory=list)
    protocol_citations: list[ProtocolCitation] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    resource_allocation: EarthquakeResourceAllocationSummary | None = None


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


class GeoJsonMultiLineString(EventContract):
    type: Literal["MultiLineString"] = "MultiLineString"
    coordinates: list[list[list[float]]]


class GeographicPoint(EventContract):
    latitude: float
    longitude: float


class FloodHydrometricStation(EventContract):
    id: int
    latitude: float
    longitude: float
    precision_m: float = Field(ge=0)
    severity_level: int = Field(ge=3, le=6)
    observed_at: AwareDatetime | None = None
    stream_match: Literal["matched", "unmatched"]


class FloodStream(EventContract):
    stream_id: int | None = None
    water_source_id: int
    name: str | None = None
    match_confidence: str | None = None
    geometry: GeoJsonLineString | GeoJsonMultiLineString
    display_semantics: Literal[
        "warning_context_not_confirmed_inundation"
    ] = "warning_context_not_confirmed_inundation"


class FloodSourceContext(EventContract):
    station: FloodHydrometricStation
    strategy: str
    stream: FloodStream | None = None


class FloodRoad(EventContract):
    segment_id: int | None = None
    source: str | None = None
    source_feature_id: str | None = None
    road_class: str | None = None
    base_class: str | None = None
    name: str | None = None
    ref: str | None = None
    bridge: bool = False
    tunnel: bool = False
    vehicle_access: str | None = None


class FloodRoadVerification(EventContract):
    status: str
    verified: bool
    reason: str | None = None
    mapbox_snap_distance_m: float | None = Field(default=None, ge=0)


class FloodResponseSite(EventContract):
    target_id: str
    source_station_id: int
    severity_level: int = Field(ge=3, le=6)
    strategy: str
    road: FloodRoad
    crossing_type: str | None = None
    urban: bool = False
    crossing_location: GeographicPoint
    allocation_location: GeographicPoint | None = None
    allocation_eligible: bool
    local_match_confidence: str
    mapbox_verification: FloodRoadVerification


class FloodAdvisory(EventContract):
    type: str
    action: str
    instruction: str
    scope: str | None = None


class FloodDetails(EventContract):
    severity_level: int = Field(ge=3, le=6)
    return_period_label: str
    sources: list[FloodSourceContext] = Field(default_factory=list)
    response_sites: list[FloodResponseSite] = Field(default_factory=list)
    allocation_ready_site_ids: list[str] = Field(default_factory=list)
    targeting_status: str
    targeting_reason: str | None = None
    allocation_target: dict[str, Any] | None = None
    advisories: list[FloodAdvisory] = Field(default_factory=list)
    resource_allocation: ResourceAllocationSummary | None = None
    limitations: list[str] = Field(default_factory=list)


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


class AirPollutionSettlementContext(EventContract):
    status: Literal["success", "unavailable"]
    outcome: Literal[
        "SUCCESS_WITH_RESULTS",
        "SUCCESS_EMPTY",
        "REFERENCE_DATA_NOT_LOADED",
        "UNAVAILABLE",
    ]
    source: Literal["shared_postgis_towns"] = "shared_postgis_towns"
    candidate_count: int = Field(default=0, ge=0)
    reason: str | None = None


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
    settlement_context: AirPollutionSettlementContext | None = None
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


class EarthquakeSharedEvent(CommonSharedEvent):
    type: Literal["earthquake"] = "earthquake"
    classification: Literal["emergency"] = "emergency"
    details: EarthquakeDetails


class FloodSharedEvent(CommonSharedEvent):
    type: Literal["flood"] = "flood"
    classification: Literal["emergency"] = "emergency"
    details: FloodDetails


class GenericSharedEvent(CommonSharedEvent):
    type: Literal["other"]
    details: dict[str, Any]


SharedEvent = Annotated[
    Union[
        AirPollutionSharedEvent,
        EarthquakeSharedEvent,
        FireSharedEvent,
        FloodSharedEvent,
        GenericSharedEvent,
    ],
    Field(discriminator="type"),
]


class SharedEventFeed(EventContract):
    events: list[SharedEvent] = Field(default_factory=list)
