import type { AllocatedStation } from '../types/events'

export type AllocationVehicleType = 'fire-truck' | 'police-car' | 'ambulance'

export type AllocationVehicle = {
  id: string
  vehicleType: AllocationVehicleType
  displayName: string
  shortLabel: string
  color: string
  modelId: string
  modelUrl: string
  headingOffset: number
  sourceName: string
  origin: { longitude: number; latitude: number }
  route: {
    coordinates: Array<[number, number]>
    distanceMeters: number
    durationSeconds: number
    estimatedArrivalAt?: string
  }
}

const VEHICLE_BY_UNIT: Record<string, Omit<AllocationVehicle, 'id' | 'sourceName' | 'origin' | 'route'>> = {
  fire_department: {
    vehicleType: 'fire-truck', displayName: 'Fire vehicle', shortLabel: 'FIRE', color: '#ef4444',
    modelId: 'allocation-fire-truck-model', modelUrl: '/models/fire_truck.glb', headingOffset: 90,
  },
  police: {
    vehicleType: 'police-car', displayName: 'Police vehicle', shortLabel: 'POLICE', color: '#3b82f6',
    modelId: 'allocation-police-car-model', modelUrl: '/models/police_car.glb', headingOffset: 0,
  },
  medical_services: {
    vehicleType: 'ambulance', displayName: 'Ambulance', shortLabel: 'MDA', color: '#22c55e',
    modelId: 'allocation-ambulance-model', modelUrl: '/models/ambulance.glb', headingOffset: 180,
  },
}

/** Converts complete allocation routes only; this adapter never requests a route. */
export function resourceAllocationSimulation(stations: readonly AllocatedStation[]): AllocationVehicle[] {
  return stations.flatMap((station) => {
    const configuration = VEHICLE_BY_UNIT[station.recommended_unit]
    const route = station.route
    const rawCoordinates = route?.geometry?.coordinates
    if (
      !configuration || !Number.isFinite(station.latitude) || !Number.isFinite(station.longitude)
      || !Array.isArray(rawCoordinates) || rawCoordinates.length < 2
      || !Number.isFinite(route?.distance_m) || !Number.isFinite(route?.duration_s)
      || (route?.duration_s ?? 0) <= 0
    ) return []

    const coordinates = rawCoordinates.flatMap((coordinate) => {
      const [longitude, latitude] = coordinate
      return Number.isFinite(longitude) && Number.isFinite(latitude)
        ? [[longitude, latitude] as [number, number]] : []
    })
    if (coordinates.length !== rawCoordinates.length) return []
    const completeRoute = route as NonNullable<typeof route>

    return [{
      id: `allocation-demo-${station.recommended_unit}-${station.database_id}`,
      ...configuration,
      sourceName: station.name,
      origin: { longitude: station.longitude, latitude: station.latitude },
      route: {
        coordinates,
        distanceMeters: completeRoute.distance_m as number,
        durationSeconds: completeRoute.duration_s as number,
        estimatedArrivalAt: completeRoute.estimated_arrival_at ?? undefined,
      },
    }]
  })
}
