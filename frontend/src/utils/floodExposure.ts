import type { EnvironmentalData } from '../types/environmentalData'
import type {
  FloodExtentGeometry,
  FloodInfrastructureExposure,
  FloodVisualizationInput,
  GeographicCoordinate,
  GeographicFlowPath,
  GeographicPolygon,
} from '../types/floodVisualization'

export type FloodExposureAssessment = {
  exposure: FloodInfrastructureExposure
  source: 'geospatial-context' | 'demo-fixture'
  assessmentBasis: 'point-in-polygon' | 'line-intersection' | 'geometry-unavailable'
  exposedStateMinutes: readonly number[]
}

type ContextFeature = {
  name?: string | null
  latitude?: number | null
  longitude?: number | null
  osm_type?: string
  osm_id?: number
}

export function contextExposureId(
  label: string,
  feature: ContextFeature,
  index: number,
) {
  return `${label}-${feature.osm_type ?? 'context'}-${feature.osm_id ?? index}`
}

function pointInRing(point: GeographicCoordinate, ring: readonly GeographicCoordinate[]) {
  let inside = false
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const currentPoint = ring[index]
    const previousPoint = ring[previous]
    const crossesLatitude = (currentPoint.latitude > point.latitude) !==
      (previousPoint.latitude > point.latitude)
    const intersectionLongitude = (previousPoint.longitude - currentPoint.longitude) *
      (point.latitude - currentPoint.latitude) /
      (previousPoint.latitude - currentPoint.latitude || Number.EPSILON) +
      currentPoint.longitude
    if (crossesLatitude && point.longitude < intersectionLongitude) inside = !inside
  }
  return inside
}

function pointInPolygon(point: GeographicCoordinate, polygon: GeographicPolygon) {
  const [outerRing, ...holes] = polygon.rings
  return Boolean(
    outerRing && pointInRing(point, outerRing) &&
    !holes.some((hole) => pointInRing(point, hole)),
  )
}

function pointInExtent(point: GeographicCoordinate, extent: FloodExtentGeometry) {
  return extent.type === 'polygon'
    ? pointInPolygon(point, extent)
    : extent.polygons.some((polygon) => pointInPolygon(point, polygon))
}

function orientation(
  first: GeographicCoordinate,
  second: GeographicCoordinate,
  third: GeographicCoordinate,
) {
  return (second.longitude - first.longitude) * (third.latitude - first.latitude) -
    (second.latitude - first.latitude) * (third.longitude - first.longitude)
}

function segmentsIntersect(
  firstStart: GeographicCoordinate,
  firstEnd: GeographicCoordinate,
  secondStart: GeographicCoordinate,
  secondEnd: GeographicCoordinate,
) {
  const overlapsBounds = Math.max(firstStart.longitude, firstEnd.longitude) >=
    Math.min(secondStart.longitude, secondEnd.longitude) &&
    Math.max(secondStart.longitude, secondEnd.longitude) >=
      Math.min(firstStart.longitude, firstEnd.longitude) &&
    Math.max(firstStart.latitude, firstEnd.latitude) >=
      Math.min(secondStart.latitude, secondEnd.latitude) &&
    Math.max(secondStart.latitude, secondEnd.latitude) >=
      Math.min(firstStart.latitude, firstEnd.latitude)
  if (!overlapsBounds) return false
  const firstSide = orientation(firstStart, firstEnd, secondStart)
  const secondSide = orientation(firstStart, firstEnd, secondEnd)
  const thirdSide = orientation(secondStart, secondEnd, firstStart)
  const fourthSide = orientation(secondStart, secondEnd, firstEnd)
  return firstSide * secondSide <= 0 && thirdSide * fourthSide <= 0
}

function pathIntersectsPolygon(path: GeographicFlowPath, polygon: GeographicPolygon) {
  if (path.coordinates.some((point) => pointInPolygon(point, polygon))) return true
  return path.coordinates.slice(0, -1).some((start, pathIndex) =>
    polygon.rings.some((ring) => ring.some((ringStart, ringIndex) =>
      segmentsIntersect(
        start,
        path.coordinates[pathIndex + 1],
        ringStart,
        ring[(ringIndex + 1) % ring.length],
      ))))
}

function polygonsIntersect(first: GeographicPolygon, second: GeographicPolygon) {
  const firstOuter = first.rings[0] ?? []
  const secondOuter = second.rings[0] ?? []
  if (firstOuter.some((point) => pointInPolygon(point, second)) ||
    secondOuter.some((point) => pointInPolygon(point, first))) return true
  return firstOuter.some((start, index) => secondOuter.some((otherStart, otherIndex) =>
    segmentsIntersect(
      start,
      firstOuter[(index + 1) % firstOuter.length],
      otherStart,
      secondOuter[(otherIndex + 1) % secondOuter.length],
    )))
}

function geometryIntersectsExtents(
  exposure: FloodInfrastructureExposure,
  extents: readonly FloodExtentGeometry[],
) {
  const geometry = exposure.geometry ?? exposure.location
  if (!geometry) return false
  if (geometry.type === 'point') {
    return extents.some((extent) => pointInExtent(geometry.coordinate, extent))
  }
  if (geometry.type === 'flow-path') {
    return extents.some((extent) => {
      const polygons = extent.type === 'polygon' ? [extent] : extent.polygons
      return polygons.some((polygon) => pathIntersectsPolygon(geometry, polygon))
    })
  }
  const polygons = geometry.type === 'polygon' ? [geometry] : geometry.polygons
  return polygons.some((polygon) => extents.some((extent) => {
    const extentPolygons = extent.type === 'polygon' ? [extent] : extent.polygons
    return extentPolygons.some((extentPolygon) => polygonsIntersect(polygon, extentPolygon))
  }))
}

function contextExposures(
  context: EnvironmentalData['geospatial_context'] | null,
): FloodInfrastructureExposure[] {
  if (!context) return []
  const points = (
    items: readonly ContextFeature[] | undefined,
    type: FloodInfrastructureExposure['type'],
    label: string,
  ) => (items ?? []).flatMap((item, index) =>
    Number.isFinite(item.latitude) && Number.isFinite(item.longitude) ? [{
      id: contextExposureId(label, item, index),
      name: item.name || undefined,
      type,
      location: {
        type: 'point' as const,
        coordinate: {
          latitude: item.latitude as number,
          longitude: item.longitude as number,
        },
      },
      exposureStatus: 'unknown' as const,
    }] : [])

  return [
    ...points(context.nearby_fire_stations, 'fire-station', 'Fire station'),
    ...points(context.nearby_police_stations, 'police-station', 'Police station'),
    ...points(context.nearby_hospitals, 'hospital', 'Hospital'),
    ...points(context.nearby_roads, 'road', 'Road'),
    ...points(context.nearby_settlements, 'settlement', 'Settlement'),
  ]
}

export function assessFloodInfrastructureExposure(
  input: FloodVisualizationInput,
  context: EnvironmentalData['geospatial_context'] | null,
): FloodExposureAssessment[] {
  const candidates = [
    ...contextExposures(context).map((exposure) => ({
      exposure,
      source: 'geospatial-context' as const,
    })),
    ...input.infrastructureExposure.map((exposure) => ({
      exposure,
      source: 'demo-fixture' as const,
    })),
  ]

  return candidates.map(({ exposure, source }) => {
    const geometry = exposure.geometry ?? exposure.location
    const assessmentBasis = geometry?.type === 'flow-path'
      ? 'line-intersection'
      : geometry?.type === 'point'
        ? 'point-in-polygon'
        : geometry
          ? 'line-intersection'
          : 'geometry-unavailable'
    const exposedStates = geometry
      ? input.states
        .filter((state) => geometryIntersectsExtents(exposure, state.floodExtents))
        .sort((left, right) => left.minutesFromNow - right.minutesFromNow)
      : []
    const exposedStateMinutes = exposedStates.map((state) => state.minutesFromNow)
    const firstExposedMinutesFromNow = exposedStateMinutes[0]

    return {
      source,
      assessmentBasis,
      exposedStateMinutes,
      exposure: {
        ...exposure,
        exposureStatus: firstExposedMinutesFromNow === undefined
          ? (geometry ? 'not-exposed' : 'unknown')
          : 'potential',
        firstExposedMinutesFromNow,
        firstExposedAt: exposedStates[0]?.timestamp,
      },
    }
  })
}
