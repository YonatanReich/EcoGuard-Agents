export type HazardKind = 'fire' | 'air_pollution' | 'flood' | 'other'
export type EventClassification = 'emergency' | 'advisory'
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type StepStatus = 'success' | 'partial' | 'unavailable' | 'failed' | 'skipped'

export type ProtocolCitation = {
  chunk_id: string
  document_id: string
  document_title: string
  source_url: string | null
  heading_path: string
  quoted_text: string
  supports: string
  verified: boolean
}

export type FireResponseAction = {
  action: string
  responsible_unit: string
  timeframe: 'immediate' | 'within_1_hour' | 'within_6_hours' | 'ongoing'
}

export type AllocationRoute = {
  status: string
  provider: string
  profile: string
  distance_m: number | null
  duration_s: number | null
  geometry: GeoJsonLineString | null
  estimated_arrival_at: string | null
  road_access_verified: boolean
  requires_field_access_confirmation: boolean
  steps_he: Array<{
    instruction?: string
    distance_m?: number
    duration_s?: number
  }>
  error?: string | null
}

export type AllocatedStation = {
  database_id: number
  name: string
  address: string | null
  unit_type: string
  recommended_unit: string
  latitude: number
  longitude: number
  distance_km: number | null
  allocation_status: string
  selection_reason: string
  route: AllocationRoute | null
}

export type ResourceAllocationSummary = {
  status: string
  routing_status: string
  requirements: Record<string, {
    requested: number
    assigned: number
    shortfall: number
  }>
  shortages: Record<string, number>
  stations: AllocatedStation[]
  errors: Array<Record<string, unknown>>
}

export type FireSpread = {
  likely: GeoJsonPolygon | null
  possible: GeoJsonPolygon | null
  heading_deg: number | null
  heading_compass: string | null
  head_rate_m_per_min: number | null
  head_distance_m: number | null
  horizon_minutes: number | null
}

export type FireExposedSettlement = {
  name: string
  name_he: string | null
  population: number | null
  exposure: 'burning' | 'likely' | 'possible'
  arrival_minutes: number | null
  distance_m: number | null
  authority_phone: string | null
  fire_district: string | null
  police_station: string | null
}

export type FireEvacuationDirective = {
  name: string
  priority: 'immediate' | 'prepare' | 'standby'
  population: number | null
  reason: string
  arrival_minutes: number | null
  authority: string | null
  authority_phone: string | null
  police_station: string | null
}

export type FireSiteAtRisk = {
  name: string
  kind: string
  category: 'hazard' | 'life_safety' | 'economic'
  exposure: 'burning' | 'likely' | 'possible'
  distance_m: number | null
}

export type FireDetectionVerdict = {
  verdict: 'confirmed' | 'probable' | 'possible' | 'doubtful' | 'unassessed'
  score: number | null
  reasons: Array<{ factor: string; points: number; detail: string }>
}

export type FireDispatchStation = {
  name: string
  district: string | null
  teams: number | null
  role: string
  request_type: string
}

export type FireDispatch = {
  grade: number | null
  grade_reason: string | null
  teams_required: number | null
  teams_assigned: number | null
  teams_shortfall: number | null
  home_district: string | null
  stations: FireDispatchStation[]
  police: Array<Record<string, unknown>>
  mda: Array<Record<string, unknown>>
  is_national_event: boolean
  national_event_basis: string | null
  limits: string[]
}

export type FireDetails = {
  detection_confidence: string | null
  fire_weather_severity: string | null
  risk_score: number | null
  risk_level: RiskLevel | null
  confidence: 'low' | 'medium' | 'high' | null
  primary_drivers: string[]
  explanation: string | null
  evidence_gaps: string[]
  recommended_units: string[]
  response_plan: string[]
  response_actions: FireResponseAction[]
  protocol_citations: ProtocolCitation[]
  resource_allocation: ResourceAllocationSummary | null

  /** Measured by the analyser and computed by the planner. Null or empty
   *  whenever the corresponding step did not run — which the UI must render
   *  as "not assessed" rather than as a zero. */
  detection: FireDetectionVerdict | null
  spread: FireSpread | null
  exposed_settlements: FireExposedSettlement[]
  sites_at_risk: FireSiteAtRisk[]
  evacuation: FireEvacuationDirective[]
  people_in_spread: number | null
  population_at_risk: Record<string, number>
  dispatch: FireDispatch | null
  incident_report: string | null
  coverage_gaps: string[]
  limits: string[]
}

export type GeoJsonPolygon = {
  type: 'Polygon'
  coordinates: number[][][]
}

export type GeoJsonLineString = {
  type: 'LineString'
  coordinates: number[][]
}

export type AirPollutionBaselineContext = {
  p95: number
  month?: number | null
  hour?: number | null
  sample_count?: number | null
  distinct_days?: number | null
  distinct_years?: number | null
  baseline_family?: string | null
  baseline_version_id?: number | string | null
  baseline_content_sha256?: string | null
}

export type MinistryAirQualityIndex = {
  station_id?: string | null
  pollutant?: string | null
  resolved_channel_id?: string | null
  station_index: number
  station_category: string
  category_color: string | null
  pollutant_sub_index: number | null
  driving_pollutant?: string | null
  averaged_concentration?: number | null
  averaging_period_minutes?: number | null
  provider_timestamp: string
  preliminary?: boolean
  source?: string
}

export type OfficialPollutantClassification = {
  classification: 'GOOD' | 'MODERATE' | 'LOW' | 'VERY_LOW' | 'UNKNOWN'
  pollutant: string
  pollutant_sub_index: number | null
  source: string
  reason: string
}

export type AirPollutionPublicationPolicy = {
  publish_to_operational_dashboard: boolean
  emphasis: 'none' | 'standard' | 'strong'
  reason: string
}

export type PossibleSourceCorrelation = {
  kind: 'possible_source_correlation'
  source_hazard: 'fire'
  source_incident_id: string
  distance_km: number | null
  bearing_deg: number | null
  lag_hours: number | null
  evidence: Record<string, unknown>
  statement: string
}

export type AirPollutionAdditionalVerification = {
  status: 'CORROBORATED' | 'NO_EXTERNAL_EVIDENCE' | 'VERIFICATION_UNAVAILABLE' | 'CONTEXT_ONLY'
  checked_at: string
  providers_checked: string[]
  evidence_references: string[]
  reason: string
  limitations: string[]
  possible_source_correlations: PossibleSourceCorrelation[]
}

export type AirPollutionWindEvidence = {
  provider: string
  source_type: 'station_observation' | 'model_forecast' | 'model_reanalysis'
  provider_location_name: string | null
  observed_or_valid_at: string
  wind_from_direction_deg: number
  wind_speed_mps: number
  gust_from_direction_deg?: number | null
  gust_speed_mps?: number | null
  direction_stddev_deg?: number | null
  reference?: string | null
  evidence_id?: string | null
}

export type TransportTimeEvidence = {
  status: 'estimated' | 'suppressed' | 'unavailable'
  seconds: number | null
  method: 'constant_wind_kinematic_screening' | null
  assumptions: string[]
  unavailable_reason?: string | null
}

export type AirPollutionSettlement = {
  id: string
  name: string
  longitude: number
  latitude: number
  inside_transport_corridor: boolean
  rank: number | null
  potential_downwind_relevance: string
  distance_m?: number | null
  transport_time: TransportTimeEvidence | null
}

export type AirPollutionSettlementContext = {
  status: 'success' | 'unavailable'
  outcome: 'SUCCESS_WITH_RESULTS' | 'SUCCESS_EMPTY' | 'REFERENCE_DATA_NOT_LOADED' | 'UNAVAILABLE'
  source: 'shared_postgis_towns'
  candidate_count: number
  reason: string | null
}

export type AirPollutionTransportScreening = {
  corridor: GeoJsonPolygon | null
  centerline: GeoJsonLineString | null
  downwind_to_direction_deg: number | null
  corridor_method?: string | null
  corridor_half_angle_deg?: number | null
  max_screening_distance_m?: number | null
  direction_stddev_deg?: number | null
  geometry_reference?: string | null
}

export type CorridorPopulationContext = {
  total_relevant_population: number
  intersected_cell_count: number
  queried_at: string
  geometry_reference: string
  dataset_reference_year?: number | null
}

export type AirPollutionRecommendation = {
  recommendation: string
  rationale: string
  responsible_authority_type: string
  resource_type: string
  timeframe: 'immediate' | 'within_1_hour' | 'within_6_hours' | 'ongoing' | 'not_specified'
  priority: 'urgent' | 'high' | 'routine' | 'monitoring' | 'not_specified'
  spatial_relevance?: string | null
}

export type VerifiedReference = {
  id: string
  document_title: string
  source_url: string | null
  quoted_text: string
  supports: string
  verified: true
}

export type ComponentUnavailableReason = {
  component: string
  reason: string
}

export type AirPollutionDetails = {
  pollutant: string
  station: {
    id: string
    name: string | null
    provider?: string | null
    channel_id?: string | null
  }
  measured_value: number
  unit: string
  observation_timestamp: string
  historical_baseline: AirPollutionBaselineContext | null
  ministry_aqi: MinistryAirQualityIndex | null
  official_pollutant_classification?: OfficialPollutantClassification | null
  publication_policy?: AirPollutionPublicationPolicy | null
  additional_verification?: AirPollutionAdditionalVerification | null
  wind: AirPollutionWindEvidence | null
  transport: AirPollutionTransportScreening | null
  relevant_settlements: AirPollutionSettlement[]
  settlement_context?: AirPollutionSettlementContext | null
  population_within_screening_corridor: CorridorPopulationContext | null
  recommendations: AirPollutionRecommendation[]
  verified_references: VerifiedReference[]
  unavailable_components: ComponentUnavailableReason[]
  limitations: string[]
  trend: 'RISING' | 'STABLE' | 'FALLING' | null
}

type CommonEvent = {
  id: string
  title: string
  description: string
  latitude: number
  longitude: number
  observed_at: string | null
  classification: EventClassification
  analysis_status: StepStatus
  planning_status: StepStatus
  processing?: {
    route: string
    status: string
    failure_stage: string | null
    failure_reason: string | null
    retryable: boolean
    attempt_count: number
    last_attempt_at: string
    processed_at: string
    using_last_successful_payload: boolean
  } | null
}

export type FireEvent = CommonEvent & {
  type: 'fire'
  details: FireDetails
}

export type AirPollutionEvent = CommonEvent & {
  type: 'air_pollution'
  classification: 'advisory'
  details: AirPollutionDetails
}

export type OtherEvent = CommonEvent & {
  type: 'flood' | 'other'
  details: Record<string, unknown>
}

export type SharedEvent = FireEvent | AirPollutionEvent | OtherEvent

export type SharedEventFeed = {
  events: SharedEvent[]
}

/** The unchanged flat fire event currently returned by GET /api/detected-events. */
export type DetectedFireEventPayload = {
  id: string
  type: string
  title: string
  description: string
  latitude: number
  longitude: number
  detection_confidence: string | null
  fire_weather_severity: string | null
  risk_score: number | null
  risk_level: RiskLevel | null
  confidence: 'low' | 'medium' | 'high' | null
  primary_drivers: string[]
  explanation: string | null
  evidence_gaps: string[]
  recommended_units: string[]
  response_plan: string[]
  response_actions: FireResponseAction[]
  protocol_citations: ProtocolCitation[]
  analysis_status: 'success' | 'failed' | 'skipped'
  planning_status: 'success' | 'failed' | 'skipped'
}

export type DetectedEventsResponse = {
  metadata: {
    timestamp: string | null
    collection_status: string
    services: Record<string, { status: string; source: string | null }>
  }
  query: {
    latitude: number
    longitude: number
    radius_km: number
    day_range: number
    include_analysis: boolean
  }
  events: DetectedFireEventPayload[]
}

/** Adapt the existing fire-only transport payload to the shared UI model. */
export function detectedFireToSharedEvent(event: DetectedFireEventPayload): FireEvent {
  return {
    id: event.id,
    type: 'fire',
    title: event.title,
    description: event.description,
    latitude: event.latitude,
    longitude: event.longitude,
    observed_at: null,
    classification:
      event.risk_level === 'critical' || event.risk_level === 'high'
        ? 'emergency'
        : 'advisory',
    analysis_status: event.analysis_status,
    planning_status: event.planning_status,
    details: {
      detection_confidence: event.detection_confidence,
      fire_weather_severity: event.fire_weather_severity,
      risk_score: event.risk_score,
      risk_level: event.risk_level,
      confidence: event.confidence,
      primary_drivers: event.primary_drivers,
      explanation: event.explanation,
      evidence_gaps: event.evidence_gaps,
      recommended_units: event.recommended_units,
      response_plan: event.response_plan,
      response_actions: event.response_actions,
      protocol_citations: event.protocol_citations,
      resource_allocation: null,
      // The legacy point-query endpoint measures none of this. Empty rather
      // than fabricated, so the UI shows "not assessed" for a fire that came
      // through the old path instead of implying nothing is at risk.
      detection: null,
      spread: null,
      exposed_settlements: [],
      sites_at_risk: [],
      evacuation: [],
      people_in_spread: null,
      population_at_risk: {},
      dispatch: null,
      incident_report: null,
      coverage_gaps: [],
      limits: [],
    },
  }
}
