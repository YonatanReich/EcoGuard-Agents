import type {
  AllocatedStation,
  FloodEvent,
  FloodResponseSite,
  FloodSourceContext,
  ResourceAllocationSummary,
} from '../types/events'

const OBSERVED_AT = '2026-09-20T08:15:00Z'

function source({
  stationId,
  latitude,
  longitude,
  precisionM,
  severity,
  stream,
}: {
  stationId: number
  latitude: number
  longitude: number
  precisionM: number
  severity: 3 | 4 | 5 | 6
  stream: { id: number; waterSourceId: number; name: string; coordinates: number[][] } | null
}): FloodSourceContext {
  return {
    station: {
      id: stationId,
      latitude,
      longitude,
      precision_m: precisionM,
      severity_level: severity,
      observed_at: OBSERVED_AT,
      stream_match: stream ? 'matched' : 'unmatched',
    },
    strategy: stream ? 'matched_stream' : 'station_buffer_primary',
    stream: stream ? {
      stream_id: stream.id,
      water_source_id: stream.waterSourceId,
      name: stream.name,
      match_confidence: 'high',
      geometry: { type: 'LineString', coordinates: stream.coordinates },
      display_semantics: 'warning_context_not_confirmed_inundation',
    } : null,
  }
}

function roadSite({
  id,
  stationId,
  severity,
  latitude,
  longitude,
  roadClass,
  name,
  ref,
  crossingType = 'at_grade',
  verified = true,
}: {
  id: string
  stationId: number
  severity: 3 | 4 | 5 | 6
  latitude: number
  longitude: number
  roadClass: string
  name: string
  ref: string | null
  crossingType?: string
  verified?: boolean
}): FloodResponseSite {
  return {
    target_id: id,
    source_station_id: stationId,
    severity_level: severity,
    strategy: 'matched_stream',
    road: {
      segment_id: Number(id.replace(/\D/g, '')) || null,
      source: 'development_fixture',
      source_feature_id: id,
      road_class: roadClass,
      base_class: roadClass.replace('_link', ''),
      name,
      ref,
      bridge: crossingType === 'bridge',
      tunnel: false,
      vehicle_access: 'yes',
    },
    crossing_type: crossingType,
    urban: latitude > 32,
    crossing_location: { latitude, longitude },
    allocation_location: verified
      ? { latitude: latitude + 0.00028, longitude: longitude + 0.00032 }
      : null,
    allocation_eligible: verified,
    local_match_confidence: 'high',
    mapbox_verification: {
      status: verified ? 'verified' : 'unverified',
      verified,
      reason: verified ? null : 'compatible_mapbox_road_not_found',
      mapbox_snap_distance_m: verified ? 18 : null,
    },
  }
}

function station({
  id,
  name,
  unit,
  latitude,
  longitude,
  destination,
  fieldAccess = false,
  fieldTarget,
}: {
  id: number
  name: string
  unit: 'police' | 'fire_department' | 'medical_services'
  latitude: number
  longitude: number
  destination: { latitude: number; longitude: number }
  fieldAccess?: boolean
  fieldTarget?: { latitude: number; longitude: number }
}): AllocatedStation {
  const labels = {
    police: 'police_station',
    fire_department: 'fire_station',
    medical_services: 'mda_station',
  }
  return {
    database_id: id,
    name,
    address: 'Development fixture address',
    unit_type: labels[unit],
    recommended_unit: unit,
    latitude,
    longitude,
    distance_km: 4.2,
    allocation_status: 'allocated',
    selection_reason: 'shortest_road_travel_time',
    route: {
      status: fieldAccess ? 'partial_offroad' : 'complete',
      provider: 'mapbox-development-fixture',
      profile: 'driving-traffic',
      distance_m: 4200,
      duration_s: 510,
      geometry: {
        type: 'LineString',
        coordinates: [
          [longitude, latitude],
          [(longitude + destination.longitude) / 2, (latitude + destination.latitude) / 2],
          [destination.longitude, destination.latitude],
        ],
      },
      destination: {
        input_location: fieldTarget ?? destination,
        snapped_location: destination,
        snap_distance_m: fieldAccess && fieldTarget ? 175 : 0,
        road_name: 'Development fixture road endpoint',
      },
      offroad_segment: fieldAccess && fieldTarget ? {
        distance_m: 175,
        geometry: {
          type: 'LineString',
          coordinates: [
            [destination.longitude, destination.latitude],
            [fieldTarget.longitude, fieldTarget.latitude],
          ],
        },
        access_verified: false,
      } : null,
      estimated_arrival_at: '2026-09-20T08:23:30Z',
      road_access_verified: !fieldAccess,
      requires_field_access_confirmation: fieldAccess,
      steps_he: [
        { instruction: 'צא מהתחנה לכיוון נקודת הגישה', distance_m: 1800, duration_s: 220 },
        { instruction: 'המשך בדרך הראשית עד לנקודת החסימה', distance_m: 2400, duration_s: 290 },
      ],
    },
  }
}

function allocation(
  stations: AllocatedStation[],
  requestedUnits: Array<'police' | 'fire_department' | 'medical_services'>,
): ResourceAllocationSummary {
  return {
    status: 'fulfilled',
    routing_status: 'complete',
    requirements: Object.fromEntries(requestedUnits.map((unit) => [
      unit,
      { requested: 1, assigned: stations.some((item) => item.recommended_unit === unit) ? 1 : 0, shortfall: 0 },
    ])),
    shortages: {},
    stations,
    errors: [],
    settlement: null,
  }
}

const kishonSites = [
  roadSite({
    id: 'preview-kishon-road-1', stationId: 501, severity: 3,
    latitude: 32.795, longitude: 35.038, roadClass: 'primary',
    name: 'דרך יגאל ידין', ref: '22', crossingType: 'bridge',
  }),
]
const kishonAccess = kishonSites[0].allocation_location!

const ayalonSites = [
  roadSite({
    id: 'preview-ayalon-road-1', stationId: 601, severity: 6,
    latitude: 32.038, longitude: 34.791, roadClass: 'motorway',
    name: 'נתיבי איילון', ref: '20', crossingType: 'overlap',
  }),
  roadSite({
    id: 'preview-ayalon-road-2', stationId: 601, severity: 6,
    latitude: 32.063, longitude: 34.793, roadClass: 'primary',
    name: 'דרך השלום', ref: null, crossingType: 'bridge',
  }),
  roadSite({
    id: 'preview-ayalon-road-3', stationId: 601, severity: 6,
    latitude: 32.087, longitude: 34.795, roadClass: 'secondary',
    name: 'רחוב פנקס', ref: null, crossingType: 'bridge',
  }),
]
const ayalonAccess = ayalonSites[0].allocation_location!

export const floodPreviewEvents = [
  {
    id: 'development-preview-flood-kishon',
    type: 'flood',
    classification: 'emergency',
    title: 'DEVELOPMENT PREVIEW – Kishon stream warning',
    description: 'Moderate Flood scenario with one verified road crossing and one police-station assignment.',
    latitude: 32.793,
    longitude: 35.055,
    observed_at: OBSERVED_AT,
    analysis_status: 'success',
    planning_status: 'success',
    details: {
      severity_level: 3,
      return_period_label: '10-year',
      sources: [source({
        stationId: 501, latitude: 32.793, longitude: 35.055,
        precisionM: 15, severity: 3,
        stream: {
          id: 51, waterSourceId: 5101, name: 'נחל קישון',
          coordinates: [[35.010, 32.801], [35.038, 32.795], [35.064, 32.788], [35.090, 32.774]],
        },
      })],
      response_sites: kishonSites,
      allocation_ready_site_ids: kishonSites.map((item) => item.target_id),
      targeting_status: 'targets_identified',
      targeting_reason: null,
      allocation_target: { target_id: kishonSites[0].target_id },
      advisories: [{
        type: 'stream_access_warning', action: 'warn_and_restrict_stream_access',
        scope: 'affected_stream', instruction: 'Warn visitors and restrict access to the specific stream under warning.',
      }],
      resource_allocation: allocation([
        station({
          id: 101, name: 'תחנת משטרת זבולון', unit: 'police',
          latitude: 32.807, longitude: 35.046, destination: kishonAccess,
        }),
      ], ['police']),
      limitations: ['DEVELOPMENT PREVIEW / NOT LIVE.', 'The stream line is not an inundation boundary.'],
    },
  },
  {
    id: 'development-preview-flood-ayalon',
    type: 'flood',
    classification: 'emergency',
    title: 'DEVELOPMENT PREVIEW – extreme Ayalon scenario',
    description: 'Extreme urban scenario with three road sites and police, fire and medical assignments.',
    latitude: 32.055,
    longitude: 34.792,
    observed_at: OBSERVED_AT,
    analysis_status: 'success',
    planning_status: 'success',
    details: {
      severity_level: 6,
      return_period_label: '100-year',
      sources: [source({
        stationId: 601, latitude: 32.055, longitude: 34.792,
        precisionM: 10, severity: 6,
        stream: {
          id: 61, waterSourceId: 6101, name: 'נחל איילון',
          coordinates: [[34.787, 31.990], [34.791, 32.038], [34.793, 32.063], [34.795, 32.087], [34.798, 32.115]],
        },
      })],
      response_sites: ayalonSites,
      allocation_ready_site_ids: ayalonSites.map((item) => item.target_id),
      targeting_status: 'targets_identified',
      targeting_reason: null,
      allocation_target: {
        target_id: ayalonSites[0].target_id,
        covered_response_site_ids: ayalonSites.map((item) => item.target_id),
      },
      advisories: [{
        type: 'stream_access_warning', action: 'warn_and_restrict_stream_access',
        scope: 'affected_stream', instruction: 'Close access to the stream and issue an extreme Flood warning.',
      }],
      resource_allocation: allocation([
        station({ id: 201, name: 'תחנת משטרת תל אביב', unit: 'police', latitude: 32.067, longitude: 34.779, destination: ayalonAccess }),
        station({ id: 202, name: 'תחנת כיבוי תל אביב', unit: 'fire_department', latitude: 32.050, longitude: 34.770, destination: ayalonAccess }),
        station({ id: 203, name: 'תחנת מד״א תל אביב', unit: 'medical_services', latitude: 32.073, longitude: 34.786, destination: ayalonAccess }),
      ], ['police', 'fire_department', 'medical_services']),
      limitations: ['DEVELOPMENT PREVIEW / NOT LIVE.', 'The stream line is not an inundation boundary.'],
    },
  },
  {
    id: 'development-preview-flood-unmatched-arava',
    type: 'flood',
    classification: 'emergency',
    title: 'DEVELOPMENT PREVIEW – unmatched Arava gauge',
    description: 'A hydrometric station without a matched stream geometry or relevant nearby road.',
    latitude: 30.735,
    longitude: 35.235,
    observed_at: OBSERVED_AT,
    analysis_status: 'success',
    planning_status: 'success',
    details: {
      severity_level: 4,
      return_period_label: '20-year',
      sources: [source({
        stationId: 701, latitude: 30.735, longitude: 35.235,
        precisionM: 250, severity: 4, stream: null,
      })],
      response_sites: [],
      allocation_ready_site_ids: [],
      targeting_status: 'no_road_targets',
      targeting_reason: 'no_relevant_road_crossings',
      allocation_target: {
        target_id: 'hydrometric-station-701',
        target_type: 'hydrometric_station_fallback',
        source_station_id: 701,
        allocation_location: { latitude: 30.735, longitude: 35.235 },
        covered_response_site_ids: [],
        requires_road_access_resolution: true,
      },
      advisories: [{
        type: 'stream_access_warning', action: 'warn_and_restrict_stream_access',
        scope: 'station_area', instruction: 'Issue a flash-Flood warning and restrict visitor access near the gauge.',
      }],
      resource_allocation: allocation([
        station({
          id: 301,
          name: 'תחנת משטרה אזורית ערבה',
          unit: 'police',
          latitude: 30.805,
          longitude: 35.245,
          destination: { latitude: 30.742, longitude: 35.220 },
          fieldAccess: true,
          fieldTarget: { latitude: 30.735, longitude: 35.235 },
        }),
      ], ['police']),
      limitations: ['DEVELOPMENT PREVIEW / NOT LIVE.', 'The dashed ring is station-location precision, not flood extent.'],
    },
  },
  {
    id: 'development-preview-flood-zin-unverified',
    type: 'flood',
    classification: 'emergency',
    title: 'DEVELOPMENT PREVIEW – Zin crossing needs verification',
    description: 'A matched stream and locally detected road crossing for which Mapbox vehicle access was not verified.',
    latitude: 30.846,
    longitude: 34.991,
    observed_at: OBSERVED_AT,
    analysis_status: 'success',
    planning_status: 'success',
    details: {
      severity_level: 5,
      return_period_label: '50-year',
      sources: [source({
        stationId: 801, latitude: 30.846, longitude: 34.991,
        precisionM: 20, severity: 5,
        stream: {
          id: 81, waterSourceId: 8101, name: 'נחל צין',
          coordinates: [[34.910, 30.875], [34.955, 30.860], [34.991, 30.846], [35.035, 30.820]],
        },
      })],
      response_sites: [roadSite({
        id: 'preview-zin-road-1', stationId: 801, severity: 5,
        latitude: 30.850, longitude: 34.980, roadClass: 'secondary',
        name: 'דרך אזורית', ref: '40', verified: false,
      })],
      allocation_ready_site_ids: [],
      targeting_status: 'verification_incomplete',
      targeting_reason: 'no_mapbox_verified_road_sites',
      allocation_target: null,
      advisories: [{
        type: 'stream_access_warning', action: 'warn_and_restrict_stream_access',
        scope: 'affected_stream', instruction: 'Close the stream to hikers while road access is verified manually.',
      }],
      resource_allocation: null,
      limitations: ['DEVELOPMENT PREVIEW / NOT LIVE.', 'The grey dashed road marker is not eligible for automatic allocation.'],
    },
  },
] satisfies FloodEvent[]
