/**
 * Provider-independent input for a future 3D flood visualization.
 *
 * External rainfall, hydrology, drainage-basin, and detection schemas should be
 * normalized into this contract before reaching the visualization layer.
 */

export type GeographicCoordinate = {
  latitude: number
  longitude: number
  heightMeters?: number
}

export type GeographicPoint = {
  type: 'point'
  coordinate: GeographicCoordinate
}

export type GeographicFlowPath = {
  type: 'flow-path'
  coordinates: readonly GeographicCoordinate[]
}

export type GeographicPolygon = {
  type: 'polygon'
  /** First ring is the boundary; subsequent rings represent holes. */
  rings: readonly (readonly GeographicCoordinate[])[]
}

export type GeographicMultiPolygon = {
  type: 'multi-polygon'
  polygons: readonly GeographicPolygon[]
}

export type FloodExtentGeometry = GeographicPolygon | GeographicMultiPolygon

export type FloodVisualizationDataMode = 'observed' | 'forecast' | 'demo'

export type FloodVisualizationSource = {
  id?: string
  name: string
  status?: 'available' | 'partial' | 'unavailable'
  observedAt?: string
  retrievedAt?: string
  details?: string
}

export type FloodVisualizationProvenance = {
  dataMode: FloodVisualizationDataMode
  operational: boolean
  sources: readonly FloodVisualizationSource[]
  limitations?: readonly string[]
}

export type FloodState = {
  minutesFromNow: number
  timestamp?: string
  timeScope: 'current' | 'forecast'
  basis: 'observed' | 'estimated'
  floodExtents: readonly FloodExtentGeometry[]
  flowPaths: readonly GeographicFlowPath[]
  waterDepthMeters?: number
  flowVelocityMetersPerSecond?: number
}

export type FloodExposureType =
  | 'road'
  | 'hospital'
  | 'police-station'
  | 'fire-station'
  | 'settlement'
  | 'infrastructure'

/**
 * Describes possible geographic exposure only. It does not represent closure,
 * evacuation, facility availability, dispatch, or resource allocation.
 */
export type FloodInfrastructureExposure = {
  id?: string
  name?: string
  type: FloodExposureType
  location?: GeographicPoint
  geometry?: GeographicPoint | GeographicFlowPath | FloodExtentGeometry
  exposureStatus: 'potential' | 'exposed' | 'not-exposed' | 'unknown'
  firstExposedMinutesFromNow?: number
  firstExposedAt?: string
}

export type FloodVisualizationInput = {
  incident: {
    id?: string | number
    eventType: 'flood'
    latitude: number
    longitude: number
    timestamp?: string
  }
  provenance: FloodVisualizationProvenance
  states: readonly FloodState[]
  infrastructureExposure: readonly FloodInfrastructureExposure[]
}
