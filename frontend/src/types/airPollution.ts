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

export type Wgs84LongitudeLatitude = [longitude: number, latitude: number]

export type AirPollutionTransportPoint = {
  type: 'Point'
  coordinates: Wgs84LongitudeLatitude
}

export type AirPollutionTransportLineString = {
  type: 'LineString'
  coordinates: Wgs84LongitudeLatitude[]
}

export type AirPollutionTransportPolygon = {
  type: 'Polygon'
  coordinates: Wgs84LongitudeLatitude[][]
}

export type AirPollutionTransportSettlement = {
  settlement_id: string
  name: string
  point: AirPollutionTransportPoint
  inside_transport_corridor: boolean
  rank?: number | null
  exclusion_reason?: string | null
  potential_downwind_relevance: string
  relevance_score: number
  geodesic_distance_m: number
  bearing_from_origin_deg: number
  angular_difference_deg: number
  along_wind_distance_m: number
  crosswind_distance_m: number
  kinematic_advection_time_seconds?: number | null
  transport_time_method?: 'constant_wind_kinematic_screening' | null
  transport_time_assumptions?: string[]
  exposure_not_confirmed: true
}

export type AirPollutionTransportSpatialOutput = {
  output_kind: 'estimated_transport_screening_geometry'
  data_status: 'success' | 'partial' | 'unavailable'
  spatial_reference: {
    srid: 4326
    crs: 'EPSG:4326'
    datum: 'WGS84'
    coordinate_order: 'longitude_latitude'
    geometry_units: 'degrees'
  }
  origin: AirPollutionTransportPoint
  centerline?: AirPollutionTransportLineString | null
  corridor_polygon?: AirPollutionTransportPolygon | null
  downwind_to_direction_deg?: number | null
  corridor_method: string
  corridor_half_angle_deg: number
  max_screening_distance_m: number
  direction_stddev_deg?: number | null
  arc_segment_count: number
  dateline_handling: 'reject_longitude_discontinuity'
  settlements?: AirPollutionTransportSettlement[]
  limitations: string[]
  exposure_not_confirmed: true
}
