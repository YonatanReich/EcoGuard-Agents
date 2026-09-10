import type { IncidentResourceSelection } from '../types/incidents'
import type { DemoResponseResource, ResponseResourceModelKey } from '../types/responseResources'

/** One presentation vehicle per unique selected facility; no availability or quantity inferred. */
export function selectedFacilitySimulation(selection?: IncidentResourceSelection): DemoResponseResource[] {
  if (!selection || !['success', 'partial'].includes(selection.status ?? '')) return []
  const configurations: [keyof NonNullable<IncidentResourceSelection['allocated_units']>, string, ResponseResourceModelKey, string][] = [
    ['fire_stations', 'fire-response', 'fire-truck', 'Fire truck'],
    ['police_stations', 'police-response', 'police-car', 'Police car'],
    ['hospitals', 'medical-response', 'ambulance', 'Ambulance'],
  ]
  const seen = new Set<string>()
  return configurations.flatMap(([group, resourceType, modelKey, displayName]) => {
    const facilities = selection.allocated_units?.[group]
    if (!Array.isArray(facilities)) return []
    return facilities.flatMap((facility): DemoResponseResource[] => {
      if (!facility || !Number.isFinite(facility.latitude) || !Number.isFinite(facility.longitude)
        || Math.abs(facility.latitude) > 90 || Math.abs(facility.longitude) > 180) return []
      // Coordinator strips OSM IDs. This ID identifies a frontend simulation only.
      const id = `demo-selected-${JSON.stringify([group, facility.name ?? '', facility.latitude, facility.longitude])}`
      if (seen.has(id)) return []
      seen.add(id)
      return [{
        id, resourceType, modelKey, displayName,
        sourceName: facility.name || 'Unnamed selected facility',
        sourceCoordinates: { latitude: facility.latitude, longitude: facility.longitude },
        allocationStatus: 'simulation',
        selectionMetadata: {
          unitType: facility.unit_type,
          distanceKm: facility.distance_km,
          selectionReason: facility.selection_reason,
        },
      }]
    })
  })
}
