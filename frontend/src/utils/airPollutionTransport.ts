import type {
  AirPollutionTransportLineString,
  AirPollutionTransportPoint,
  AirPollutionTransportSettlement,
  AirPollutionTransportSpatialOutput,
  Wgs84LongitudeLatitude,
} from '../types/airPollution'
import type { IncidentDetails } from '../types/incidents'
import { isAirPollutionEvent } from './airPollutionEvents'

type UnknownRecord = Record<string, unknown>

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null
}

function isLongitudeLatitude(value: unknown): value is Wgs84LongitudeLatitude {
  return Array.isArray(value)
    && value.length === 2
    && typeof value[0] === 'number'
    && Number.isFinite(value[0])
    && value[0] >= -180
    && value[0] <= 180
    && typeof value[1] === 'number'
    && Number.isFinite(value[1])
    && value[1] >= -90
    && value[1] <= 90
}

function isPoint(value: unknown): value is AirPollutionTransportPoint {
  return isRecord(value)
    && value.type === 'Point'
    && isLongitudeLatitude(value.coordinates)
}

function isLineString(value: unknown): value is AirPollutionTransportLineString {
  return isRecord(value)
    && value.type === 'LineString'
    && Array.isArray(value.coordinates)
    && value.coordinates.length >= 2
    && value.coordinates.every(isLongitudeLatitude)
}

function positionsEqual(left: Wgs84LongitudeLatitude, right: Wgs84LongitudeLatitude) {
  return left[0] === right[0] && left[1] === right[1]
}

function hasLongitudeDiscontinuity(coordinates: Wgs84LongitudeLatitude[]) {
  return coordinates.slice(1).some(
    (position, index) => Math.abs(position[0] - coordinates[index][0]) > 180,
  )
}

function isPolygon(value: unknown): boolean {
  if (!isRecord(value)
    || value.type !== 'Polygon'
    || !Array.isArray(value.coordinates)
    || value.coordinates.length !== 1) return false

  const ring = value.coordinates[0]
  return Array.isArray(ring)
    && ring.length >= 4
    && ring.every(isLongitudeLatitude)
    && positionsEqual(ring[0], ring[ring.length - 1])
    && !hasLongitudeDiscontinuity(ring)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isSettlement(value: unknown): value is AirPollutionTransportSettlement {
  return isRecord(value)
    && typeof value.settlement_id === 'string'
    && typeof value.name === 'string'
    && isPoint(value.point)
    && typeof value.inside_transport_corridor === 'boolean'
    && typeof value.potential_downwind_relevance === 'string'
    && isFiniteNumber(value.geodesic_distance_m)
    && isFiniteNumber(value.bearing_from_origin_deg)
    && isFiniteNumber(value.angular_difference_deg)
    && isFiniteNumber(value.along_wind_distance_m)
    && isFiniteNumber(value.crosswind_distance_m)
    && (value.kinematic_advection_time_seconds == null
      || isFiniteNumber(value.kinematic_advection_time_seconds))
}

function hasSpatialReference(value: unknown): boolean {
  return isRecord(value)
    && value.srid === 4326
    && value.crs === 'EPSG:4326'
    && value.datum === 'WGS84'
    && value.coordinate_order === 'longitude_latitude'
    && value.geometry_units === 'degrees'
}

function isRenderableTransportOutput(
  value: unknown,
): value is AirPollutionTransportSpatialOutput {
  if (!isRecord(value)
    || value.output_kind !== 'estimated_transport_screening_geometry'
    || (value.data_status !== 'success' && value.data_status !== 'partial')
    || value.exposure_not_confirmed !== true
    || !hasSpatialReference(value.spatial_reference)
    || !isPoint(value.origin)
    || !isLineString(value.centerline)
    || hasLongitudeDiscontinuity(value.centerline.coordinates)
    || !isPolygon(value.corridor_polygon)
    || !isFiniteNumber(value.downwind_to_direction_deg)
    || value.downwind_to_direction_deg < 0
    || value.downwind_to_direction_deg >= 360
    || !isFiniteNumber(value.corridor_half_angle_deg)
    || value.corridor_half_angle_deg <= 0
    || value.corridor_half_angle_deg >= 180
    || !isFiniteNumber(value.max_screening_distance_m)
    || value.max_screening_distance_m <= 0
    || !Number.isInteger(value.arc_segment_count)
    || (value.arc_segment_count as number) < 1
    || value.dateline_handling !== 'reject_longitude_discontinuity') return false

  return value.settlements === undefined
    || (Array.isArray(value.settlements) && value.settlements.every(isSettlement))
}

/** Return only complete backend-derived geometry for the selected pollution event. */
export function transportOutputForEvent(
  event: IncidentDetails | null | undefined,
): AirPollutionTransportSpatialOutput | null {
  if (!isAirPollutionEvent(event) || !event?.air_pollution_transport) return null
  return isRenderableTransportOutput(event.air_pollution_transport)
    ? event.air_pollution_transport
    : null
}
