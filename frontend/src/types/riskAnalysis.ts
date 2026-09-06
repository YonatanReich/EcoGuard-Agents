export type RiskFactor = {
  feature: string
  statement: string
}

export type CurrentRiskAssessment = {
  status: 'available' | 'unavailable' | 'error'
  score: number | null
  level: 'low' | 'medium' | 'high' | null
  semantics: string
  main_factors: RiskFactor[]
  reason: string | null
  missing_runtime_inputs: string[]
  model_version: string | null
}

export type FireRiskAssessment = {
  status: 'available' | 'unavailable' | 'error'
  location: {
    latitude: number
    longitude: number
  }
  current_risk: CurrentRiskAssessment
  actual_fire_detection: {
    included: boolean
    semantics: string
  }
}
