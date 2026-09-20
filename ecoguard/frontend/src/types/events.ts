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
  destination?: {
    input_location?: GeographicPoint
    snapped_location?: GeographicPoint
    snap_distance_m?: number | null
    road_name?: string | null
  } | null
  offroad_segment?: {
    distance_m: number
    geometry: GeoJsonLineString
    access_verified: boolean
  } | null
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

export type AllocationSettlement = {
  population: number | null
  households: number | null
  authority: string | null
  authority_type: string | null
  authority_phone: string | null
  authority_address: string | null
  authority_website: string | null
  area_km2: number | null
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
  settlement: AllocationSettlement | null
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
}

export type GeoJsonPolygon = {
  type: 'Polygon'
  coordinates: number[][][]
}

export type GeoJsonLineString = {
  type: 'LineString'
  coordinates: number[][]
}

export type GeoJsonMultiLineString = {
  type: 'MultiLineString'
  coordinates: number[][][]
}

export type GeographicPoint = {
  latitude: number
  longitude: number
}

export type FloodSourceContext = {
  station: GeographicPoint & {
    id: number
    precision_m: number
    severity_level: 3 | 4 | 5 | 6
    observed_at: string | null
    stream_match: 'matched' | 'unmatched'
  }
  strategy: string
  stream: {
    stream_id: number | null
    water_source_id: number
    name: string | null
    match_confidence: string | null
    geometry: GeoJsonLineString | GeoJsonMultiLineString
    display_semantics: 'warning_context_not_confirmed_inundation'
  } | null
}

export type FloodResponseSite = {
  target_id: string
  source_station_id: number
  severity_level: 3 | 4 | 5 | 6
  strategy: string
  road: {
    segment_id: number | null
    source: string | null
    source_feature_id: string | null
    road_class: string | null
    base_class: string | null
    name: string | null
    ref: string | null
    bridge: boolean
    tunnel: boolean
    vehicle_access: string | null
  }
  crossing_type: string | null
  urban: boolean
  crossing_location: GeographicPoint
  allocation_location: GeographicPoint | null
  allocation_eligible: boolean
  local_match_confidence: string
  mapbox_verification: {
    status: string
    verified: boolean
    reason: string | null
    mapbox_snap_distance_m: number | null
  }
}

export type FloodDetails = {
  severity_level: 3 | 4 | 5 | 6
  return_period_label: string
  sources: FloodSourceContext[]
  response_sites: FloodResponseSite[]
  allocation_ready_site_ids: string[]
  targeting_status: string
  targeting_reason: string | null
  allocation_target: Record<string, unknown> | null
  advisories: Array<{ type: string; action: string; instruction: string; scope: string | null }>
  resource_allocation: ResourceAllocationSummary | null
  response_plan?: Record<string, unknown> | null
  change_type?: string | null
  threshold_transition?: string | null
  response_refresh_required?: boolean | null
  existing_response_preserved?: boolean
  limitations: string[]
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

export type FloodEvent = CommonEvent & {
  type: 'flood'
  classification: 'emergency'
  details: FloodDetails
}

export type OtherEvent = CommonEvent & {
  type: 'other'
  details: Record<string, unknown>
}

export type SharedEvent = FireEvent | AirPollutionEvent | FloodEvent | OtherEvent

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
    },
  }
}
