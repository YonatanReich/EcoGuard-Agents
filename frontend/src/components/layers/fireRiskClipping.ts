import serviceAreaText from '../../../../data/reference/ecoguard_service_area.geojson?raw'
import type { NationalRiskCell } from '../fireRiskScan'

type Position = [number, number]
type Ring = Position[]
type PolygonCoordinates = Ring[]
type ServiceGeometry = {
  type: 'Polygon' | 'MultiPolygon'
  coordinates: PolygonCoordinates | PolygonCoordinates[]
}

const HALF_CELL_KM = 2.5
const serviceArea = JSON.parse(serviceAreaText) as {
  features: Array<{ geometry: ServiceGeometry }>
}
const geometry = serviceArea.features[0].geometry
const servicePolygons: PolygonCoordinates[] = geometry.type === 'Polygon'
  ? [geometry.coordinates as PolygonCoordinates]
  : geometry.coordinates as PolygonCoordinates[]

function pointOnSegment(point: Position, start: Position, end: Position) {
  const cross = (point[0] - start[0]) * (end[1] - start[1])
    - (point[1] - start[1]) * (end[0] - start[0])
  return Math.abs(cross) <= 1e-10
    && point[0] >= Math.min(start[0], end[0]) - 1e-10
    && point[0] <= Math.max(start[0], end[0]) + 1e-10
    && point[1] >= Math.min(start[1], end[1]) - 1e-10
    && point[1] <= Math.max(start[1], end[1]) + 1e-10
}

function ringContainsOrTouches(ring: Ring, point: Position) {
  let inside = false
  for (let index = 0; index < ring.length - 1; index += 1) {
    const start = ring[index]
    const end = ring[index + 1]
    if (pointOnSegment(point, start, end)) return true
    if ((start[1] > point[1]) !== (end[1] > point[1])) {
      const crossing = (end[0] - start[0]) * (point[1] - start[1])
        / (end[1] - start[1]) + start[0]
      if (point[0] < crossing) inside = !inside
    }
  }
  return inside
}

function polygonContainsOrTouches(polygon: PolygonCoordinates, point: Position) {
  if (!ringContainsOrTouches(polygon[0], point)) return false
  return !polygon.slice(1).some((hole) => ringContainsOrTouches(hole, point))
}

function serviceAreaContainsOrTouches(point: Position) {
  return servicePolygons.some((polygon) => polygonContainsOrTouches(polygon, point))
}

function clipRing(ring: Ring, left: number, bottom: number, right: number, top: number): Ring {
  let points = ring.slice(0, ring.length > 1 && ring[0][0] === ring.at(-1)?.[0]
    && ring[0][1] === ring.at(-1)?.[1] ? -1 : undefined)

  const clip = (
    input: Ring,
    inside: (point: Position) => boolean,
    intersection: (start: Position, end: Position) => Position,
  ) => {
    if (input.length === 0) return []
    const output: Ring = []
    let previous = input[input.length - 1]
    let previousInside = inside(previous)
    input.forEach((current) => {
      const currentInside = inside(current)
      if (currentInside) {
        if (!previousInside) output.push(intersection(previous, current))
        output.push(current)
      } else if (previousInside) output.push(intersection(previous, current))
      previous = current
      previousInside = currentInside
    })
    return output
  }
  const vertical = (longitude: number) => (start: Position, end: Position): Position => {
    const portion = (longitude - start[0]) / (end[0] - start[0])
    return [longitude, start[1] + portion * (end[1] - start[1])]
  }
  const horizontal = (latitude: number) => (start: Position, end: Position): Position => {
    const portion = (latitude - start[1]) / (end[1] - start[1])
    return [start[0] + portion * (end[0] - start[0]), latitude]
  }

  points = clip(points, (point) => point[0] >= left, vertical(left))
  points = clip(points, (point) => point[0] <= right, vertical(right))
  points = clip(points, (point) => point[1] >= bottom, horizontal(bottom))
  points = clip(points, (point) => point[1] <= top, horizontal(top))
  if (points.length >= 3) points.push(points[0])
  return points
}

function rectangle(cell: NationalRiskCell) {
  const latitudeDelta = HALF_CELL_KM / 111.32
  const longitudeDelta = HALF_CELL_KM / (111.32 * Math.cos(cell.latitude * Math.PI / 180))
  const left = cell.longitude - longitudeDelta
  const right = cell.longitude + longitudeDelta
  const bottom = cell.latitude - latitudeDelta
  const top = cell.latitude + latitudeDelta
  const ring: Ring = [[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]
  return { left, right, bottom, top, ring }
}

export function clippedCellFeature(cell: NationalRiskCell) {
  const bounds = rectangle(cell)
  const corners = bounds.ring.slice(0, 4)
  if (corners.every(serviceAreaContainsOrTouches)) {
    return {
      type: 'Feature' as const,
      properties: { ...cell },
      geometry: { type: 'Polygon' as const, coordinates: [bounds.ring] },
    }
  }

  const polygons = servicePolygons.flatMap((polygon) => {
    const outer = clipRing(polygon[0], bounds.left, bounds.bottom, bounds.right, bounds.top)
    if (outer.length < 4) return []
    const holes = polygon.slice(1)
      .map((hole) => clipRing(hole, bounds.left, bounds.bottom, bounds.right, bounds.top))
      .filter((hole) => hole.length >= 4)
    return [[outer, ...holes]]
  })
  if (polygons.length === 0) return null
  return {
    type: 'Feature' as const,
    properties: { ...cell },
    geometry: polygons.length === 1
      ? { type: 'Polygon' as const, coordinates: polygons[0] }
      : { type: 'MultiPolygon' as const, coordinates: polygons },
  }
}

export function clippedFireRiskFeatureCollection(cells: NationalRiskCell[]) {
  return {
    type: 'FeatureCollection' as const,
    features: cells.map(clippedCellFeature).filter((feature) => feature !== null),
  }
}

export function featureCollectionBounds(collection: ReturnType<typeof clippedFireRiskFeatureCollection>) {
  const positions: Position[] = []
  const visit = (value: unknown) => {
    if (Array.isArray(value) && value.length >= 2
      && typeof value[0] === 'number' && typeof value[1] === 'number') {
      positions.push([value[0], value[1]])
    } else if (Array.isArray(value)) value.forEach(visit)
  }
  collection.features.forEach((feature) => visit(feature.geometry.coordinates))
  if (positions.length === 0) return null
  return [
    [Math.min(...positions.map((point) => point[0])), Math.min(...positions.map((point) => point[1]))],
    [Math.max(...positions.map((point) => point[0])), Math.max(...positions.map((point) => point[1]))],
  ] as [[number, number], [number, number]]
}
