export type ResourceCoordinate = {
  latitude: number
  longitude: number
  heightMeters?: number
}

export type ResponseResourceModelKey = 'ambulance' | 'fire-truck' | 'police-car'

export type AllocatedResponseResource = {
  id: string
  resourceType: string
  displayName: string
  sourceName?: string
  sourceCoordinates: ResourceCoordinate
  currentCoordinates?: ResourceCoordinate
  allocationStatus: 'allocated' | 'dispatched' | 'en-route' | 'on-scene'
  route?: {
    coordinates: ResourceCoordinate[]
    distanceMeters?: number
    durationSeconds?: number
  }
  modelKey?: ResponseResourceModelKey
}

export type IncidentRiskArea = {
  radiusMeters: number
  color?: string
}

/** A presentation vehicle, never an operational allocation or dispatch. */
export type DemoResponseResource = Omit<AllocatedResponseResource, 'allocationStatus'> & {
  allocationStatus: 'simulation'
  selectionMetadata?: {
    unitType?: string
    distanceKm?: number
    selectionReason?: string
  }
}
