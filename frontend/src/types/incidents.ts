export type IncidentRiskLevel = 'low' | 'medium' | 'high' | 'critical'

export type IncidentStepStatus = 'success' | 'failed' | 'skipped'

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
