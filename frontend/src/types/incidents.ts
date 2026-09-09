import type {
  AirPollutionAnomaly,
  AirPollutionCorrelationEvidence,
  AirPollutionResponsePlan,
  AirPollutionSpatialContext,
  AirPollutionTransportSpatialOutput,
} from './airPollution'

export type IncidentRiskLevel = 'low' | 'medium' | 'high' | 'critical'

export type IncidentStepStatus = 'success' | 'failed' | 'skipped'

export type SelectedResponseFacility = {
  name?: string | null
  latitude: number
  longitude: number
  unit_type?: string
  distance_km?: number
  selection_reason?: string
}

export type IncidentResourceSelection = {
  status?: string
  allocation_needed?: boolean
  reason?: string
  rationale?: string
  alert_radius_km?: number | null
  allocated_units?: {
    fire_stations?: SelectedResponseFacility[]
    police_stations?: SelectedResponseFacility[]
    hospitals?: SelectedResponseFacility[]
  }
  shortages?: Record<string, number>
  unsupported_units?: string[]
  errors?: { facility_type: string; reason: string; message: string }[]
}

export type IncidentResponseAction = {
  action: string
  responsible_unit: string
  timeframe: 'immediate' | 'within_1_hour' | 'within_6_hours' | 'ongoing'
}

export type IncidentProtocolCitation = {
  chunk_id: string
  document_id: string
  document_title: string
  source_url: string | null
  heading_path: string
  quoted_text: string
  supports: string
  verified: boolean
}

export type DetectedEventsResponse = {
  metadata: {
    timestamp: string | null
    collection_status: string
    services: Record<string, {
      status: string
      source: string | null
      last_attempted_at?: string | null
      last_successful_collection_at?: string | null
      stale?: boolean
      observation_count?: number
      excluded_count?: number
      errors?: string[]
    }>
  }
  query: {
    latitude: number
    longitude: number
    radius_km: number
    day_range: number
    include_analysis: boolean
  }
  events: IncidentDetails[]
}

export type IncidentDetails = {
  id: string | number
  type: string
  title: string
  description?: string
  latitude: number
  longitude: number
  detection_confidence?: string | null
  fire_weather_severity?: string | null
  detection_source?: string | null
  risk_score?: number | null
  risk_level?: IncidentRiskLevel | null
  confidence?: 'low' | 'medium' | 'high' | null
  primary_drivers?: string[]
  recommended_units?: string[]
  response_plan?: string | string[]
  response_actions?: IncidentResponseAction[]
  explanation?: string | null
  evidence_gaps?: string[]
  protocol_citations?: IncidentProtocolCitation[]
  analysis_status?: IncidentStepStatus
  planning_status?: IncidentStepStatus
  allocated_resources?: IncidentResourceSelection
  /** EA-307 anomaly payload when type is air_pollution. */
  anomaly?: AirPollutionAnomaly
  /** EA-310 proximity context. The lookup radius is not an exposure zone. */
  spatial_context?: AirPollutionSpatialContext
  /** EA-311 heuristic evidence; it does not establish causation. */
  correlation_evidence?: AirPollutionCorrelationEvidence
  /** EA-312 decision support; never dispatch or availability. */
  pollution_response_plan?: AirPollutionResponsePlan
  /** Optional EA-322 geometry; absent until the prediction runtime is connected. */
  air_pollution_transport?: AirPollutionTransportSpatialOutput | null
  /** Refresh provenance for retained last-known pollution state. */
  air_pollution_runtime?: {
    status: string
    stale: boolean
    last_successful_collection_at?: string | null
  }
}

export type AirPollutionIncidentDetails = IncidentDetails & {
  type: 'air_pollution'
  anomaly: AirPollutionAnomaly
}

export type EventEvidence = {
  category: 'environmental' | 'geographic' | 'infrastructure' | 'detection'
  source: string
  status: 'available' | 'partial' | 'unavailable'
  summary: string
}

export type AgentPipelineStatus = {
  name: string
  emphasis: 'primary' | 'downstream'
  status: 'available' | 'partial' | 'unavailable' | 'in-progress' | 'not-started'
  detail: string
}
