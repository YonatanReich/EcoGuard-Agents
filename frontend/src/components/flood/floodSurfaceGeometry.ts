import {
  Cartesian3,
  Cartographic,
  Math as CesiumMath,
  PolygonHierarchy,
  Scene,
} from 'cesium'

import type {
  FloodState,
  GeographicCoordinate,
  GeographicPolygon,
} from '../../types/floodVisualization'

const SAMPLE_SPACING_METERS = 18
const MAX_LOCAL_HEIGHT_DEVIATION_METERS = 7
const SMOOTHING_RADIUS = 3
export const FLOOD_SURFACE_CLEARANCE_METERS = 0.65
export const FLOW_EFFECT_CLEARANCE_METERS = 1.05

export type PreparedFloodSurface = {
  waterHierarchies: PolygonHierarchy[]
  flowPaths: Cartesian3[][]
  origin: Cartesian3
  downstreamPoint: Cartesian3
}

function approximateDistanceMeters(
  start: GeographicCoordinate,
  end: GeographicCoordinate,
) {
  const meanLatitude = CesiumMath.toRadians((start.latitude + end.latitude) / 2)
  const latitudeMeters = (end.latitude - start.latitude) * 111_320
  const longitudeMeters = (end.longitude - start.longitude) * 111_320 * Math.cos(meanLatitude)
  return Math.hypot(latitudeMeters, longitudeMeters)
}

function densifyPath(coordinates: readonly GeographicCoordinate[]) {
  if (coordinates.length < 2) return [...coordinates]

  return coordinates.slice(0, -1).flatMap((start, index) => {
    const end = coordinates[index + 1]
    const steps = Math.max(1, Math.ceil(
      approximateDistanceMeters(start, end) / SAMPLE_SPACING_METERS,
    ))
    return Array.from({ length: steps }, (_, step) => {
      const progress = step / steps
      return {
        latitude: start.latitude + (end.latitude - start.latitude) * progress,
        longitude: start.longitude + (end.longitude - start.longitude) * progress,
      }
    })
  }).concat(coordinates[coordinates.length - 1])
}

function median(values: number[]) {
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle]
}

function resolveMissingHeights(heights: Array<number | undefined>) {
  const sampledIndexes = heights.flatMap((height, index) =>
    Number.isFinite(height) ? [index] : [])
  if (sampledIndexes.length === 0) return null

  return heights.map((height, index) => {
    if (Number.isFinite(height)) return height as number
    const previous = [...sampledIndexes].reverse().find((sampled) => sampled < index)
    const next = sampledIndexes.find((sampled) => sampled > index)
    if (previous !== undefined && next !== undefined) {
      const progress = (index - previous) / (next - previous)
      return (heights[previous] as number) +
        ((heights[next] as number) - (heights[previous] as number)) * progress
    }
    return heights[previous ?? next as number] as number
  })
}

function rejectLocalOutliers(heights: number[]) {
  return heights.map((height, index) => {
    const local = heights.slice(Math.max(0, index - 2), index + 3)
    const localMedian = median(local)
    return Math.abs(height - localMedian) > MAX_LOCAL_HEIGHT_DEVIATION_METERS
      ? localMedian
      : height
  })
}

function smoothHeights(heights: number[]) {
  return heights.map((_, index) => {
    const local = heights.slice(
      Math.max(0, index - SMOOTHING_RADIUS),
      index + SMOOTHING_RADIUS + 1,
    )
    return local.reduce((total, height) => total + height, 0) / local.length
  })
}

function closestCenterlineIndex(
  coordinate: GeographicCoordinate,
  centerline: readonly GeographicCoordinate[],
) {
  let closestIndex = 0
  let closestDistance = Number.POSITIVE_INFINITY
  centerline.forEach((candidate, index) => {
    const distance = approximateDistanceMeters(coordinate, candidate)
    if (distance < closestDistance) {
      closestDistance = distance
      closestIndex = index
    }
  })
  return closestIndex
}

function polygonHierarchyAtChannelHeight(
  polygon: GeographicPolygon,
  centerline: readonly GeographicCoordinate[],
  channelHeights: readonly number[],
) {
  const rings = polygon.rings.map((ring) => ring.map((coordinate) => {
    const centerlineIndex = closestCenterlineIndex(coordinate, centerline)
    return Cartesian3.fromDegrees(
      coordinate.longitude,
      coordinate.latitude,
      channelHeights[centerlineIndex] + FLOOD_SURFACE_CLEARANCE_METERS,
    )
  }))
  const outer = rings[0]
  if (!outer || outer.length < 3) return null
  const holes = rings.slice(1)
    .filter((ring) => ring.length >= 3)
    .map((ring) => new PolygonHierarchy(ring))
  return new PolygonHierarchy(outer, holes)
}

export async function prepareFloodSurface(
  scene: Scene,
  state: FloodState,
): Promise<PreparedFloodSurface | null> {
  const primaryFlowPath = state.flowPaths.find((path) => path.coordinates.length >= 2)
  if (!primaryFlowPath || !scene.sampleHeightSupported) return null

  const centerline = densifyPath(primaryFlowPath.coordinates)
  const cartographics = centerline.map(({ longitude, latitude }) =>
    Cartographic.fromDegrees(longitude, latitude))
  const samples = await scene.sampleHeightMostDetailed(cartographics)
  const resolved = resolveMissingHeights(samples.map((sample) => sample?.height))
  if (!resolved) return null

  const channelHeights = smoothHeights(rejectLocalOutliers(resolved))
  const polygons = state.floodExtents.flatMap((extent) =>
    extent.type === 'polygon' ? [extent] : extent.polygons)
  const waterHierarchies = polygons.flatMap((polygon) => {
    const hierarchy = polygonHierarchyAtChannelHeight(
      polygon,
      centerline,
      channelHeights,
    )
    return hierarchy ? [hierarchy] : []
  })
  if (waterHierarchies.length === 0) return null

  const flowPath = centerline.map((coordinate, index) => Cartesian3.fromDegrees(
    coordinate.longitude,
    coordinate.latitude,
    channelHeights[index] + FLOW_EFFECT_CLEARANCE_METERS,
  ))

  return {
    waterHierarchies,
    flowPaths: [flowPath],
    origin: flowPath[0],
    downstreamPoint: flowPath[flowPath.length - 1],
  }
}
