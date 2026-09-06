export type IncidentDetails = {
  id: string | number
  type: string
  title: string
  description?: string
  latitude: number
  longitude: number
  risk_score?: number
  risk_level?: string
  recommended_units?: string[]
  response_plan?: string | string[]
  explanation?: string
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
