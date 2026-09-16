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
  wind: AirPollutionWindEvidence | null
  transport: AirPollutionTransportScreening | null
  relevant_settlements: AirPollutionSettlement[]
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
    },
  }
}
