import type {
  FloodState,
  FloodVisualizationInput,
  GeographicCoordinate,
} from '../types/floodVisualization'

/**
 * Deterministic Yarkon-corridor visualization fixture only. Coordinates,
 * extents, exposure, and timing are not measured or predicted flood data.
 */
const FLOW_CENTERLINE = [
  { latitude: 32.0998859, longitude: 34.8043456 },
  { latitude: 32.0998881, longitude: 34.8032704 },
  { latitude: 32.0998913, longitude: 34.8016621 },
  { latitude: 32.1000968, longitude: 34.800918 },
  { latitude: 32.1001808, longitude: 34.8003953 },
  { latitude: 32.1001483, longitude: 34.799829 },
  { latitude: 32.09954, longitude: 34.79862 },
  { latitude: 32.09894, longitude: 34.79742 },
  { latitude: 32.0984537, longitude: 34.796484 },
  { latitude: 32.09808, longitude: 34.79508 },
  { latitude: 32.09772, longitude: 34.7937 },
  { latitude: 32.0973999, longitude: 34.7924358 },
  { latitude: 32.09708, longitude: 34.79042 },
  { latitude: 32.0967304, longitude: 34.7883926 },
] as const satisfies readonly GeographicCoordinate[]

type StateDefinition = {
  minutes: number
  timestamp: string
  points: number
  leftWidthsMeters: readonly number[]
  rightWidthsMeters: readonly number[]
}

const STATE_DEFINITIONS = [
  { minutes: 0, timestamp: '2025-01-01T08:00:00Z', points: 4,
    leftWidthsMeters: [12, 14, 15, 13], rightWidthsMeters: [12, 14, 15, 13] },
  { minutes: 30, timestamp: '2025-01-01T08:30:00Z', points: 6,
    leftWidthsMeters: [13, 15, 16, 17, 18, 16],
    rightWidthsMeters: [13, 15, 16, 17, 18, 16] },
  { minutes: 60, timestamp: '2025-01-01T09:00:00Z', points: 8,
    leftWidthsMeters: [14, 16, 17, 18, 20, 22, 27, 20],
    rightWidthsMeters: [14, 16, 17, 18, 20, 21, 23, 19] },
  { minutes: 120, timestamp: '2025-01-01T10:00:00Z', points: 10,
    leftWidthsMeters: [15, 17, 18, 20, 24, 35, 43, 34, 27, 21],
    rightWidthsMeters: [15, 17, 18, 20, 22, 26, 31, 29, 25, 20] },
  { minutes: 240, timestamp: '2025-01-01T12:00:00Z', points: 12,
    leftWidthsMeters: [16, 18, 20, 23, 29, 45, 58, 51, 39, 33, 42, 25],
    rightWidthsMeters: [16, 18, 20, 23, 27, 34, 45, 48, 37, 31, 35, 24] },
  { minutes: 360, timestamp: '2025-01-01T14:00:00Z', points: 14,
    leftWidthsMeters: [17, 19, 22, 26, 34, 52, 70, 64, 48, 42, 56, 62, 48, 28],
    rightWidthsMeters: [17, 19, 22, 26, 31, 41, 56, 65, 51, 43, 49, 54, 44, 27] },
] as const satisfies readonly StateDefinition[]

function offsetFromCenterline(
  path: readonly GeographicCoordinate[],
  index: number,
  distanceMeters: number,
) {
  const coordinate = path[index]
  const previous = path[Math.max(0, index - 1)]
  const next = path[Math.min(path.length - 1, index + 1)]
  const meanLatitudeRadians = coordinate.latitude * Math.PI / 180
  const eastMeters = (next.longitude - previous.longitude) *
    111_320 * Math.cos(meanLatitudeRadians)
  const northMeters = (next.latitude - previous.latitude) * 111_320
  const length = Math.hypot(eastMeters, northMeters) || 1
  const normalEast = -northMeters / length
  const normalNorth = eastMeters / length

  return {
    latitude: coordinate.latitude + normalNorth * distanceMeters / 111_320,
    longitude: coordinate.longitude + normalEast * distanceMeters /
      (111_320 * Math.cos(meanLatitudeRadians)),
  }
}

function corridorRing(definition: StateDefinition) {
  const path = FLOW_CENTERLINE.slice(0, definition.points)
  const leftBank = path.map((_, index) => offsetFromCenterline(
    path,
    index,
    definition.leftWidthsMeters[index],
  ))
  const rightBank = path.map((_, index) => offsetFromCenterline(
    path,
    index,
    -definition.rightWidthsMeters[index],
  )).reverse()
  return [...leftBank, ...rightBank, leftBank[0]]
}

const states: FloodState[] = STATE_DEFINITIONS.map((definition, index) => ({
  minutesFromNow: definition.minutes,
  timestamp: definition.timestamp,
  timeScope: index === 0 ? 'current' : 'forecast',
  basis: index === 0 ? 'observed' : 'estimated',
  floodExtents: [{ type: 'polygon', rings: [corridorRing(definition)] }],
  flowPaths: [{
    type: 'flow-path',
    coordinates: FLOW_CENTERLINE.slice(0, definition.points),
  }],
}))

export const demoFloodScenario = {
  incident: {
    id: 'demo-yarkon-flood-propagation-001',
    eventType: 'flood',
    latitude: FLOW_CENTERLINE[0].latitude,
    longitude: FLOW_CENTERLINE[0].longitude,
    timestamp: '2025-01-01T08:00:00Z',
  },
  provenance: {
    dataMode: 'demo',
    operational: false,
    sources: [{
      id: 'deterministic-yarkon-visualization-fixture',
      name: 'EcoGuard Yarkon corridor demo fixture',
      status: 'available',
      observedAt: '2025-01-01T08:00:00Z',
      details: 'Synthetic visualization geometry; not hydrological analysis or evidence.',
    }],
    limitations: [
      'DEMO / ESTIMATED / NOT OPERATIONAL.',
      'Geometry does not use rainfall, terrain, drainage, catchment, or flood-model calculations.',
      'Rendered surface alignment is visual placement, not predicted water-surface elevation.',
      'Infrastructure exposure does not indicate closure, evacuation, availability, or dispatch.',
    ],
  },
  states,
  infrastructureExposure: [
    {
      id: 'demo-yarkon-road-exposure-001', name: 'Demo bridge approach', type: 'road',
      location: { type: 'point', coordinate: FLOW_CENTERLINE[10] },
      exposureStatus: 'potential', firstExposedMinutesFromNow: 120,
      firstExposedAt: '2025-01-01T10:00:00Z',
    },
    {
      id: 'demo-yarkon-infrastructure-exposure-001',
      name: 'Demo riverside utility asset', type: 'infrastructure',
      location: { type: 'point', coordinate: FLOW_CENTERLINE[12] },
      exposureStatus: 'exposed', firstExposedMinutesFromNow: 360,
      firstExposedAt: '2025-01-01T14:00:00Z',
    },
  ],
} satisfies FloodVisualizationInput
