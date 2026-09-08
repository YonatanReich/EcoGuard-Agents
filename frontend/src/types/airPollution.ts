export type AirPollutionSeverity = 'low' | 'medium' | 'high' | 'critical'

export type AirPollutionObservation = {
  pollutant: string
  value: number
  unit: string
  provider_pollutant_id?: string | null
  provider_unit?: string | null
  observed_at?: string | null
  source_id?: string | null
}

export type AirPollutionSource = {
  source_id: string
  source_name: string
  source_type?: string | null
  observed_at?: string | null
  reference?: string | null
  metadata?: {
    station_id?: string | null
    channel_id?: string | null
    [key: string]: unknown
  }
}

export type AirPollutionEvidence = {
  evidence_id: string
  source_id: string
  evidence_type: string
  summary: string
  observed_at?: string | null
}

export type AirPollutionAnomaly = {
  detection_id: string
  anomaly_type: 'air_pollution'
  observed_at: string
  detected_at: string
  location: { latitude: number; longitude: number }
  pollutant_observations: AirPollutionObservation[]
  severity: AirPollutionSeverity
  confidence: number
  explanation: string
  anomaly_reasons?: string[]
  sources: AirPollutionSource[]
  supporting_evidence?: AirPollutionEvidence[]
  assessment?: {
    detection_methods?: string[]
    provider_aqi_value?: number | null
    provider_aqi_category?: string | null
    preliminary?: boolean
    limitations?: string[]
  } | null
}

export type PollutionNearbyFeature = {
  name?: string | null
  type?: string | null
  ref?: string | null
  osm_id?: string | number | null
  osm_type?: 'node' | 'way' | 'relation' | null
  latitude?: number | null
  longitude?: number | null
  distance_km?: number | null
}

export type AirPollutionSpatialContext = {
  location: { latitude: number; longitude: number }
  lookup_radius_km: number
  status: 'success' | 'partial' | 'unavailable'
  source?: string | null
  collected_at?: string | null
  provider_collection_status?: string | null
  nearby_settlements?: PollutionNearbyFeature[]
  nearby_roads?: PollutionNearbyFeature[]
  nearby_hospitals?: PollutionNearbyFeature[]
  nearby_police_stations?: PollutionNearbyFeature[]
  nearby_fire_stations?: PollutionNearbyFeature[]
  missing_layers?: string[]
  limitations?: string[]
  errors?: string[]
}

export type AirPollutionCorrelationEvidence = {
  candidate_match: boolean
  duplicate_kind: 'exact' | 'same_station_observation' | 'near_duplicate_candidate' | 'none'
  temporal_distance_seconds: number
  spatial_distance_km: number
  matching_signals: string[]
  conflicting_signals: string[]
  shared_geographic_features: string[]
  limitations: string[]
}

export type AirPollutionResponseAction = {
  recommendation: string
  responsible_authority_type: string
  resource_type: string
  timeframe: string
  priority: string
  supporting_chunk_ids: string[]
}

export type AirPollutionProtocolReference = {
  chunk_id: string
  document_id: string
  document_title: string
  source_url: string
  heading_path: string
  quoted_text: string
  supports: string
  verified: true
}

export type AirPollutionResponsePlan = {
  status: 'success' | 'failed' | 'skipped'
  reason?: string | null
  summary?: string | null
  recommended_authority_types?: string[]
  recommended_resource_types?: string[]
  actions?: AirPollutionResponseAction[]
  assumptions?: string[]
  evidence_gaps?: string[]
  limitations?: string[]
  protocol_references?: AirPollutionProtocolReference[]
}
