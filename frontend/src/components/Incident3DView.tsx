import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BoundingSphere,
  CallbackProperty,
  Cartesian2,
  Cartesian3,
  Cartographic,
  ClockRange,
  Color,
  ConstantProperty,
  createGooglePhotorealistic3DTileset,
  DistanceDisplayCondition,
  ExtrapolationType,
  HeadingPitchRange,
  Ion,
  JulianDate,
  LabelStyle,
  Matrix4,
  Math as CesiumMath,
  NearFarScalar,
  PolylineGlowMaterialProperty,
  Quaternion,
  SampledPositionProperty,
  Scene,
  SceneTransforms,
  Transforms,
  VelocityOrientationProperty,
  VerticalOrigin,
  Viewer,
} from 'cesium'

import type { EnvironmentalData } from '../types/environmentalData'
import {
  attachFloodWaterRenderer,
  type FloodWaterRenderer,
  type PreparedFloodTimelineState,
} from './flood/FloodWaterRenderer'
import {
  prepareFloodSurface,
  type PreparedFloodSurface,
} from './flood/floodSurfaceGeometry'
import type { FloodVisualizationInput } from '../types/floodVisualization'
import type { IncidentDetails } from '../types/incidents'
import type {
  AllocatedResponseResource,
  IncidentRiskArea,
  ResponseResourceModelKey,
} from '../types/responseResources'
import {
  assessFloodInfrastructureExposure,
  contextExposureId,
  type FloodExposureAssessment,
} from '../utils/floodExposure'

import './incident-3d-view.css'

export type OperationalIncident3DProps = {
  incident: IncidentDetails
  context: EnvironmentalData['geospatial_context'] | null
  allocatedResources?: readonly AllocatedResponseResource[]
  riskArea?: IncidentRiskArea | null
  floodVisualization?: {
    input: FloodVisualizationInput
  } | null
}

type InfrastructureMarker = {
  id: string
  name: string
  latitude: number
  longitude: number
  category: 'Fire station' | 'Police station' | 'Hospital' | 'Road'
  color: Color
  symbol: string
}

const FLOOD_PLAYBACK_DURATION_SECONDS = 30

function formatFloodTime(minutesFromNow: number) {
  if (minutesFromNow <= 0) return 'CURRENT'
  if (minutesFromNow < 60) return `+${Math.round(minutesFromNow)} MIN`
  if (minutesFromNow % 60 === 0) {
    const hours = minutesFromNow / 60
    return `+${hours} ${hours === 1 ? 'HOUR' : 'HOURS'}`
  }
  const hours = Math.floor(minutesFromNow / 60)
  const minutes = Math.round(minutesFromNow % 60)
  return `+${hours}H ${minutes}M`
}

type InitializationStage =
  | 'Cesium Viewer creation'
  | 'Google Photorealistic 3D Tiles creation'
  | 'Tileset primitive attachment'
  | 'Incident entity creation'
  | 'Flood water primitive creation'
  | 'Infrastructure entity creation'
  | 'Allocated resource entity creation'
  | 'Camera positioning'

type SanitizedInitializationError = {
  stage: InitializationStage
  name: string
  message: string
}

type RoutedResource = Omit<AllocatedResponseResource, 'allocationStatus'> & {
  allocationStatus: AllocatedResponseResource['allocationStatus'] | 'simulation'
  mode: 'verified' | 'demo'
  sourceFacility: string
}

type RouteResult = {
  distance: number
  duration: number
  geometry: { coordinates: [number, number][] }
}

type SurfaceRoutePoint = {
  longitude: number
  latitude: number
  surfaceHeight: number
  routeHeight: number
  vehicleHeight: number
  heightSource: 'sampled' | 'interpolated'
}

type SurfaceAwareRoute = RouteResult & {
  surfacePoints: SurfaceRoutePoint[]
}

type SimulationSummary = {
  id: string
  displayName: string
  sourceFacility: string
  mode: 'verified' | 'demo'
  routeDistanceKm?: number
  estimatedDurationSeconds?: number
  remainingDistanceKm?: number
  remainingSeconds?: number
  simulationRemainingSeconds?: number
  status: 'READY' | 'EN ROUTE' | 'ON SCENE' | 'ROUTE UNAVAILABLE'
}

const RESOURCE_MODELS: Record<ResponseResourceModelKey, string> = {
  ambulance: '/models/ambulance.glb',
  'fire-truck': '/models/fire_truck.glb',
  'police-car': '/models/police_car.glb',
}

const RESOURCE_ROUTE_COLORS: Record<ResponseResourceModelKey, Color> = {
  'fire-truck': Color.ORANGERED,
  'police-car': Color.DODGERBLUE,
  ambulance: Color.LIMEGREEN,
}

const RESOURCE_ORIGIN_SYMBOLS: Record<ResponseResourceModelKey, string> = {
  'fire-truck': 'F',
  'police-car': 'P',
  ambulance: 'H',
}

const RESOURCE_MODEL_HEADING_OFFSETS_DEGREES: Record<ResponseResourceModelKey, number> = {
  'fire-truck': 90,
  'police-car': 0,
  ambulance: 0,
}

function resourceColor(resource: Pick<AllocatedResponseResource, 'modelKey'>) {
  return resource.modelKey ? RESOURCE_ROUTE_COLORS[resource.modelKey] : Color.CYAN
}

function createResourceOrientation(
  position: SampledPositionProperty,
  modelKey?: ResponseResourceModelKey,
) {
  const velocityOrientation = new VelocityOrientationProperty(position)
  const headingOffsetDegrees = modelKey
    ? RESOURCE_MODEL_HEADING_OFFSETS_DEGREES[modelKey]
    : 0
  if (headingOffsetDegrees === 0) return velocityOrientation

  const correction = Quaternion.fromAxisAngle(
    Cartesian3.UNIT_Z,
    CesiumMath.toRadians(headingOffsetDegrees),
  )
  return new CallbackProperty((time) => {
    const baseOrientation = velocityOrientation.getValue(time)
    return baseOrientation
      ? Quaternion.multiply(baseOrientation, correction, new Quaternion())
      : undefined
  }, false)
}

const INCIDENT_STYLES: Record<string, { color: Color; symbol: string }> = {
  wildfire: { color: Color.ORANGERED, symbol: '●' },
  fire: { color: Color.ORANGERED, symbol: '●' },
  flood: { color: Color.DODGERBLUE, symbol: '◆' },
  storm: { color: Color.DARKORCHID, symbol: '▲' },
  sandstorm: { color: Color.SANDYBROWN, symbol: '▲' },
  'air pollution': { color: Color.DARKGRAY, symbol: '●' },
}

type SimulationSpeed = 1 | 2 | 4 | 8
const ROUTE_CLEARANCE_METERS = 1.5
const VEHICLE_CLEARANCE_METERS = 4
const FOLLOW_BEHIND_METERS = 200
const FOLLOW_ABOVE_METERS = 160
const FOLLOW_LOOK_AHEAD_METERS = 10
const FOLLOW_SMOOTHING = 0.08

// Cesium caches the ion metadata Resource used by the Google tiles helper. Serializing
// only the factory call prevents overlapping fetches through that Resource while still
// returning a distinct, viewer-owned tileset for every initialization generation.
let googleTilesetCreationQueue: Promise<void> = Promise.resolve()

function createViewerOwnedGoogleTileset() {
  const request = googleTilesetCreationQueue
    .catch(() => undefined)
    .then(() => createGooglePhotorealistic3DTileset())
  googleTilesetCreationQueue = request.then(
    () => undefined,
    () => undefined,
  )
  return request
}

function interpolateMissingSurfaceHeights(heights: Array<number | undefined>) {
  const sampledIndexes = heights.flatMap((height, index) =>
    Number.isFinite(height) ? [index] : [])
  if (sampledIndexes.length === 0) return null

  return heights.map((height, index) => {
    if (Number.isFinite(height)) {
      return { height: height as number, source: 'sampled' as const }
    }

    const previousIndex = [...sampledIndexes].reverse().find((item) => item < index)
    const nextIndex = sampledIndexes.find((item) => item > index)
    if (previousIndex !== undefined && nextIndex !== undefined) {
      const interpolation = (index - previousIndex) / (nextIndex - previousIndex)
      return {
        height: (heights[previousIndex] as number) +
          ((heights[nextIndex] as number) - (heights[previousIndex] as number)) * interpolation,
        source: 'interpolated' as const,
      }
    }

    const nearestIndex = previousIndex ?? nextIndex as number
    return { height: heights[nearestIndex] as number, source: 'interpolated' as const }
  })
}

async function createSurfaceAwareRoute(
  scene: Scene,
  route: RouteResult,
): Promise<SurfaceAwareRoute> {
  if (!scene.sampleHeightSupported) {
    throw new Error('Detailed 3D surface height sampling is not supported by this browser.')
  }

  const cartographics = route.geometry.coordinates.map(([longitude, latitude]) =>
    Cartographic.fromDegrees(longitude, latitude))
  const sampledPositions = await scene.sampleHeightMostDetailed(cartographics)
  const resolvedHeights = interpolateMissingSurfaceHeights(
    sampledPositions.map((position) => position?.height),
  )
  if (!resolvedHeights) {
    throw new Error('No photorealistic surface heights could be sampled for this route.')
  }

  return {
    ...route,
    surfacePoints: route.geometry.coordinates.map(([longitude, latitude], index) => {
      const resolved = resolvedHeights[index]
      return {
        longitude,
        latitude,
        surfaceHeight: resolved.height,
        routeHeight: resolved.height + ROUTE_CLEARANCE_METERS,
        vehicleHeight: resolved.height + VEHICLE_CLEARANCE_METERS,
        heightSource: resolved.source,
      }
    }),
  }
}

function routeBearing(start: Cartesian3, end: Cartesian3) {
  const from = Cartographic.fromCartesian(start)
  const to = Cartographic.fromCartesian(end)
  const longitudeDelta = to.longitude - from.longitude
  return Math.atan2(
    Math.sin(longitudeDelta) * Math.cos(to.latitude),
    Math.cos(from.latitude) * Math.sin(to.latitude) -
      Math.sin(from.latitude) * Math.cos(to.latitude) * Math.cos(longitudeDelta),
  )
}

async function fetchRoute(
  resource: Pick<
    AllocatedResponseResource,
    'currentCoordinates' | 'route' | 'sourceCoordinates'
  >,
  incident: IncidentDetails,
): Promise<RouteResult> {
  if (
    resource.route?.coordinates &&
    resource.route.coordinates.length > 1 &&
    resource.route.distanceMeters !== undefined &&
    resource.route.durationSeconds !== undefined
  ) {
    return {
      distance: resource.route.distanceMeters,
      duration: resource.route.durationSeconds,
      geometry: {
        coordinates: resource.route.coordinates.map(
          ({ longitude, latitude }) => [longitude, latitude] as [number, number],
        ),
      },
    }
  }

  const start = resource.currentCoordinates ?? resource.sourceCoordinates
  const url = `https://router.project-osrm.org/route/v1/driving/${start.longitude},${start.latitude};${incident.longitude},${incident.latitude}?overview=full&geometries=geojson`
  const response = await fetch(url, { signal: AbortSignal.timeout(12_000) })
  if (!response.ok) throw new Error(`Routing service returned HTTP ${response.status}`)
  const payload = await response.json() as { code?: string; routes?: RouteResult[] }
  if (payload.code !== 'Ok' || !payload.routes?.[0]) throw new Error('No driving route was returned')
  return payload.routes[0]
}

function formatDuration(seconds?: number) {
  if (seconds === undefined) return 'Unavailable'
  const minutes = Math.max(1, Math.ceil(seconds / 60))
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} hr ${minutes % 60} min`
}

function supportsWebGl() {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch {
    return false
  }
}

function sanitizeInitializationError(
  error: unknown,
  stage: InitializationStage,
  token: string,
): SanitizedInitializationError {
  const name = error instanceof Error ? error.name : 'UnknownError'
  const unsafeMessage = error instanceof Error ? error.message : String(error)
  const message = unsafeMessage
    .replaceAll(token, '[credential redacted]')
    .replace(/https?:\/\/\S+/gi, '[request URL redacted]')
    .replace(/((?:access_token|token|key)=)[^\s&]+/gi, '$1[credential redacted]')

  return {
    stage,
    name,
    message: message || 'No error message was provided.',
  }
}

function asInfrastructureMarkers(
  context: EnvironmentalData['geospatial_context'] | null,
  includeRoads = false,
): InfrastructureMarker[] {
  if (!context) return []

  const convert = (
    items: EnvironmentalData['geospatial_context']['nearby_hospitals'],
    category: InfrastructureMarker['category'],
    color: Color,
    symbol: string,
  ) => (items ?? [])
    .filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude))
    .map((item, index) => ({
      id: contextExposureId(category, item, index),
      name: item.name || `Unnamed ${category.toLowerCase()}`,
      latitude: item.latitude,
      longitude: item.longitude,
      category,
      color,
      symbol,
    }))

  const facilities = [
    ...convert(context.nearby_fire_stations, 'Fire station', Color.ORANGE, 'F'),
    ...convert(context.nearby_police_stations, 'Police station', Color.DODGERBLUE, 'P'),
    ...convert(context.nearby_hospitals, 'Hospital', Color.LIMEGREEN, 'H'),
  ]
  const roads = includeRoads ? (context.nearby_roads ?? []).flatMap((road, index) =>
    Number.isFinite(road.latitude) && Number.isFinite(road.longitude) ? [{
      id: contextExposureId('Road', road, index),
      name: road.name || road.ref || 'Unnamed nearby road',
      latitude: road.latitude as number,
      longitude: road.longitude as number,
      category: 'Road' as const,
      color: Color.SLATEGRAY,
      symbol: 'R',
    }] : []) : []
  return [...facilities, ...roads]
}

function setExposureMarkerVisibility(
  viewer: Viewer,
  assessments: readonly FloodExposureAssessment[],
  minutesFromNow: number,
) {
  assessments.forEach(({ exposure }) => {
    const marker = viewer.entities.getById(`flood-exposure-${exposure.id}`)
    if (marker) {
      marker.show = exposure.firstExposedMinutesFromNow !== undefined &&
        minutesFromNow >= exposure.firstExposedMinutesFromNow
    }
  })
}

function exposureMarkerCoordinate(assessment: FloodExposureAssessment) {
  const geometry = assessment.exposure.location ?? assessment.exposure.geometry
  return geometry?.type === 'point' ? geometry.coordinate : null
}

function selectDemoResources(
  context: EnvironmentalData['geospatial_context'] | null,
  incident: IncidentDetails,
): RoutedResource[] {
  if (!context) return []

  const nearest = (
    items: EnvironmentalData['geospatial_context']['nearby_hospitals'],
  ) => [...(items ?? [])]
    .filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude))
    .sort((left, right) => {
      const leftDistance = Math.hypot(left.latitude - incident.latitude, left.longitude - incident.longitude)
      const rightDistance = Math.hypot(right.latitude - incident.latitude, right.longitude - incident.longitude)
      return leftDistance - rightDistance
    })[0]

  const configurations = [
    { facility: nearest(context.nearby_fire_stations), type: 'fire-response', modelKey: 'fire-truck' as const, label: 'Fire truck' },
    { facility: nearest(context.nearby_police_stations), type: 'police-response', modelKey: 'police-car' as const, label: 'Police car' },
    { facility: nearest(context.nearby_hospitals), type: 'medical-response', modelKey: 'ambulance' as const, label: 'Ambulance' },
  ]

  return configurations.flatMap(({ facility, type, modelKey, label }) => facility ? [{
    id: `demo-${modelKey}-${facility.osm_id ?? facility.name}`,
    resourceType: type,
    displayName: label,
    sourceFacility: facility.name || `Nearby ${label.toLowerCase()} facility`,
    sourceCoordinates: { latitude: facility.latitude, longitude: facility.longitude },
    allocationStatus: 'simulation' as const,
    modelKey,
    mode: 'demo' as const,
  }] : [])
}

function Incident3DView({
  incident,
  context,
  allocatedResources = [],
  riskArea = null,
  floodVisualization = null,
}: OperationalIncident3DProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Viewer | null>(null)
  const [sceneState, setSceneState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [sceneError, setSceneError] = useState<SanitizedInitializationError | null>(null)
  const [retryRequestId, setRetryRequestId] = useState(0)
  const initializationGenerationRef = useRef(0)
  const tilesetRequestRef = useRef<{
    generation: number
    promise: ReturnType<typeof createViewerOwnedGoogleTileset>
  } | null>(null)
  const [demoActive, setDemoActive] = useState(false)
  const [simulationSummaries, setSimulationSummaries] = useState<SimulationSummary[]>([])
  const [followedResourceId, setFollowedResourceId] = useState<string | null>(null)
  const followedResourceIdRef = useRef<string | null>(null)
  const followHeadingRef = useRef<number | null>(null)
  const followCameraPositionRef = useRef<Cartesian3 | null>(null)
  const followTargetRef = useRef<Cartesian3 | null>(null)
  const followDiagnosticTimeRef = useRef(0)
  const [isSimulationPanelCollapsed, setIsSimulationPanelCollapsed] = useState(false)
  const [simulationSpeed, setSimulationSpeed] = useState<SimulationSpeed>(1)
  const simulationSpeedRef = useRef<SimulationSpeed>(1)
  const floodRendererRef = useRef<FloodWaterRenderer | null>(null)
  const preparedFloodStatesRef = useRef<PreparedFloodTimelineState[]>([])
  const floodTimeRef = useRef(0)
  const [floodTimeMinutes, setFloodTimeMinutes] = useState(0)
  const [isFloodPlaying, setIsFloodPlaying] = useState(false)
  const floodOrbitFrameRef = useRef(0)
  const [isFloodOrbiting, setIsFloodOrbiting] = useState(false)
  const hasWebGl = useMemo(() => supportsWebGl(), [])
  const token = import.meta.env.VITE_CESIUM_ION_TOKEN?.trim()
  const isFloodMode = floodVisualization !== null
  const sceneIncident = useMemo<IncidentDetails>(() => isFloodMode
    ? {
        id: floodVisualization.input.incident.id ?? 'flood-visualization',
        type: floodVisualization.input.incident.eventType,
        title: 'Demo flood visualization',
        latitude: floodVisualization.input.incident.latitude,
        longitude: floodVisualization.input.incident.longitude,
        risk_level: undefined,
      }
    : incident, [floodVisualization, incident, isFloodMode])
  const infrastructure = useMemo(
    () => asInfrastructureMarkers(context, isFloodMode),
    [context, isFloodMode],
  )
  const floodStates = useMemo(
    () => [...(floodVisualization?.input.states ?? [])]
      .sort((left, right) => left.minutesFromNow - right.minutesFromNow),
    [floodVisualization],
  )
  const floodMaxMinutes = floodStates.at(-1)?.minutesFromNow ?? 0
  const exposureAssessments = useMemo(
    () => floodVisualization
      ? assessFloodInfrastructureExposure(floodVisualization.input, context)
      : [],
    [context, floodVisualization],
  )
  const displayedExposureAssessments = useMemo(() => [...exposureAssessments]
    .sort((left, right) => {
      const leftTime = left.exposure.firstExposedMinutesFromNow ?? Number.POSITIVE_INFINITY
      const rightTime = right.exposure.firstExposedMinutesFromNow ?? Number.POSITIVE_INFINITY
      return leftTime - rightTime
    })
    .slice(0, 12), [exposureAssessments])
  const activeResources = useMemo<RoutedResource[]>(() => {
    if (isFloodMode) return []
    if (allocatedResources.length > 0) {
      return allocatedResources.map((resource) => ({
        ...resource,
        mode: 'verified',
        sourceFacility: resource.sourceName ?? resource.displayName,
      }))
    }
    return demoActive ? selectDemoResources(context, incident) : []
  }, [allocatedResources, context, demoActive, incident, isFloodMode])

  useEffect(() => {
    if (!token || !hasWebGl || !containerRef.current) return

    const generation = ++initializationGenerationRef.current
    let cancelled = false
    let viewer: Viewer | null = null
    let floodRenderer: FloodWaterRenderer | null = null
    let preparedFloodSurface: PreparedFloodSurface | null = null
    let initializationStage: InitializationStage = 'Cesium Viewer creation'
    const logLifecycle = (event: string) => {
      if (import.meta.env.DEV) {
        console.debug('[Incident3DView] lifecycle', { generation, event })
      }
    }
    const isCurrentGeneration = () =>
      !cancelled && initializationGenerationRef.current === generation
    setSceneState('loading')
    setSceneError(null)

    const initialize = async () => {
      try {
        Ion.defaultAccessToken = token
        viewer = new Viewer(containerRef.current as HTMLElement, {
          animation: false,
          baseLayerPicker: false,
          fullscreenButton: false,
          geocoder: false,
          globe: false,
          homeButton: false,
          infoBox: true,
          navigationHelpButton: false,
          sceneModePicker: false,
          selectionIndicator: true,
          timeline: false,
        })
        logLifecycle('viewer created')
        viewerRef.current = viewer
        const cameraController = viewer.scene.screenSpaceCameraController
        cameraController.minimumZoomDistance = 80
        cameraController.maximumZoomDistance = 50_000
        if (isFloodMode) {
          cameraController.enableRotate = true
          cameraController.enableTilt = true
          cameraController.enableZoom = true
          cameraController.enableTranslate = true
          cameraController.enableLook = true
        }

        initializationStage = 'Google Photorealistic 3D Tiles creation'
        let tilesetRequest = tilesetRequestRef.current
        if (!tilesetRequest || tilesetRequest.generation !== generation) {
          tilesetRequest = {
            generation,
            promise: createViewerOwnedGoogleTileset(),
          }
          tilesetRequestRef.current = tilesetRequest
          logLifecycle('tileset request started')
        } else {
          logLifecycle('tileset request reused')
        }
        const tileset = await tilesetRequest.promise
        if (!isCurrentGeneration() || viewer.isDestroyed()) {
          logLifecycle('stale initialization ignored')
          if (!tileset.isDestroyed()) tileset.destroy()
          return
        }
        initializationStage = 'Tileset primitive attachment'
        viewer.scene.primitives.add(tileset)
        logLifecycle('tileset attached')

        initializationStage = 'Incident entity creation'
        const incidentStyle = INCIDENT_STYLES[sceneIncident.type.toLowerCase()] ?? {
          color: Color.GOLD,
          symbol: '◆',
        }
        viewer.entities.add({
          id: `incident-${sceneIncident.id}`,
          name: sceneIncident.title || `${sceneIncident.type} incident`,
          position: Cartesian3.fromDegrees(
            sceneIncident.longitude,
            sceneIncident.latitude,
            18,
          ),
          point: {
            color: incidentStyle.color,
            outlineColor: Color.WHITE,
            outlineWidth: isFloodMode ? 2 : 3,
            pixelSize: isFloodMode ? 10 : 18,
            scaleByDistance: isFloodMode
              ? new NearFarScalar(300, 1, 8_000, 0.45)
              : new NearFarScalar(500, 1.5, 30_000, 0.7),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: isFloodMode
              ? 'Origin'
              : `${incidentStyle.symbol} ${incident.type || 'Environmental'} incident\n${incident.risk_level || 'Severity not provided'}`,
            font: isFloodMode ? '11px sans-serif' : 'bold 16px sans-serif',
            fillColor: Color.WHITE,
            outlineColor: Color.BLACK,
            outlineWidth: isFloodMode ? 2 : 4,
            pixelOffset: new Cartesian2(0, isFloodMode ? -20 : -34),
            scale: isFloodMode ? 0.55 : 0.8,
            style: LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: VerticalOrigin.BOTTOM,
            distanceDisplayCondition: new DistanceDisplayCondition(
              0,
              isFloodMode ? 3_500 : 50_000,
            ),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        })

        if (floodVisualization) {
          initializationStage = 'Flood water primitive creation'
          const preparedTimelineStates: PreparedFloodTimelineState[] = []
          for (const state of floodStates) {
            const surface = await prepareFloodSurface(viewer.scene, state)
            if (!isCurrentGeneration() || viewer.isDestroyed()) return
            if (surface) {
              preparedTimelineStates.push({
                minutesFromNow: state.minutesFromNow,
                surface,
              })
            }
          }
          preparedFloodSurface = preparedTimelineStates[0]?.surface ?? null
          if (!preparedFloodSurface || preparedTimelineStates.length === 0) {
            throw new Error('The flood surface could not be aligned with the 3D scene.')
          }
          floodRenderer = attachFloodWaterRenderer(viewer.scene, preparedTimelineStates)
          floodRenderer.setTimeMinutes(floodTimeRef.current)
          floodRendererRef.current = floodRenderer
          preparedFloodStatesRef.current = preparedTimelineStates
        }

        if (riskArea && Number.isFinite(riskArea.radiusMeters) && riskArea.radiusMeters > 0) {
          viewer.entities.add({
            id: `incident-risk-area-${incident.id}`,
            position: Cartesian3.fromDegrees(incident.longitude, incident.latitude),
            ellipse: {
              semiMajorAxis: riskArea.radiusMeters,
              semiMinorAxis: riskArea.radiusMeters,
              material: Color.fromCssColorString(riskArea.color ?? '#f59e0b').withAlpha(0.18),
              outline: true,
              outlineColor: Color.fromCssColorString(riskArea.color ?? '#f59e0b'),
            },
          })
        }

        initializationStage = 'Infrastructure entity creation'
        infrastructure.forEach((marker) => {
          const labelOffset = marker.category === 'Fire station'
            ? new Cartesian2(-24, -22)
            : marker.category === 'Police station'
              ? new Cartesian2(24, -8)
              : marker.category === 'Hospital'
                ? new Cartesian2(0, 20)
                : new Cartesian2(18, 12)
          viewer?.entities.add({
            id: marker.id,
            name: marker.name,
            position: Cartesian3.fromDegrees(marker.longitude, marker.latitude, 10),
            point: {
              color: marker.color,
              outlineColor: Color.WHITE,
              outlineWidth: 2,
              pixelSize: 10,
              scaleByDistance: new NearFarScalar(400, 1.05, 50_000, 0.42),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            label: {
              text: marker.symbol,
              font: 'bold 11px sans-serif',
              fillColor: Color.WHITE,
              outlineColor: Color.BLACK,
              outlineWidth: 3,
              pixelOffset: labelOffset,
              scale: 0.7,
              style: LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: VerticalOrigin.BOTTOM,
              distanceDisplayCondition: new DistanceDisplayCondition(0, 30_000),
              scaleByDistance: new NearFarScalar(300, 0.85, 30_000, 0.4),
              showBackground: true,
              backgroundColor: marker.color.withAlpha(0.72),
              backgroundPadding: new Cartesian2(4, 3),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          })
        })

        if (isFloodMode) {
          exposureAssessments.forEach((assessment) => {
            const coordinate = exposureMarkerCoordinate(assessment)
            if (!coordinate || !assessment.exposure.id) return
            const hasInfrastructureMarker = infrastructure.some(
              (marker) => marker.id === assessment.exposure.id,
            )
            if (assessment.source === 'demo-fixture' ||
              (!hasInfrastructureMarker &&
                assessment.exposure.firstExposedMinutesFromNow !== undefined)) {
              const isDemoFixture = assessment.source === 'demo-fixture'
              viewer?.entities.add({
                id: `${isDemoFixture ? 'demo-fixture' : 'flood-context'}-${assessment.exposure.id}`,
                name: isDemoFixture
                  ? `${assessment.exposure.name ?? 'Demo infrastructure'} (demo fixture)`
                  : assessment.exposure.name ?? 'Nearby infrastructure',
                description: isDemoFixture
                  ? 'Synthetic visualization fixture · not real infrastructure.'
                  : 'Real geospatial context · exposure is estimated from a representative point.',
                position: Cartesian3.fromDegrees(
                  coordinate.longitude,
                  coordinate.latitude,
                  11,
                ),
                point: {
                  color: isDemoFixture ? Color.MEDIUMPURPLE : Color.SLATEBLUE,
                  outlineColor: Color.WHITE,
                  outlineWidth: 1,
                  pixelSize: 8,
                  disableDepthTestDistance: Number.POSITIVE_INFINITY,
                },
              })
            }
            viewer?.entities.add({
              id: `flood-exposure-${assessment.exposure.id}`,
              name: `${assessment.exposure.name ?? 'Infrastructure'} · potential demo exposure`,
              description: 'Estimated geographic intersection only · not a closure or operational status.',
              position: Cartesian3.fromDegrees(
                coordinate.longitude,
                coordinate.latitude,
                14,
              ),
              show: assessment.exposure.firstExposedMinutesFromNow !== undefined &&
                floodTimeRef.current >= assessment.exposure.firstExposedMinutesFromNow,
              point: {
                color: Color.TRANSPARENT,
                outlineColor: Color.fromCssColorString('#fbbf24'),
                outlineWidth: 4,
                pixelSize: 23,
                scaleByDistance: new NearFarScalar(300, 1.1, 20_000, 0.55),
                disableDepthTestDistance: Number.POSITIVE_INFINITY,
              },
            })
          })
        }

        initializationStage = 'Allocated resource entity creation'
        setSimulationSummaries(activeResources.map((resource) => ({
          id: resource.id,
          displayName: resource.displayName,
          sourceFacility: resource.sourceFacility,
          mode: resource.mode,
          status: 'READY',
        })))
        const routeScene = viewer.scene
        const routeResults = await Promise.all(activeResources.map(async (resource) => {
          try {
            const route = await fetchRoute(resource, incident)
            return {
              resource,
              route: await createSurfaceAwareRoute(routeScene, route),
              error: null,
            }
          } catch (error: unknown) {
            if (import.meta.env.DEV) {
              console.warn('[Incident3DView] resource route unavailable', {
                resourceId: resource.id,
                reason: error instanceof Error ? error.message : 'Route unavailable',
              })
            }
            return {
              resource,
              route: null,
              error: error instanceof Error ? error.message : 'Route unavailable',
            }
          }
        }))
        if (!isCurrentGeneration() || viewer.isDestroyed()) return

        const startTime = JulianDate.now()
        const routedAnimations: Array<{
          resource: RoutedResource
          entityId: string
          route: SurfaceAwareRoute
          simulatedDuration: number
        }> = []

        routeResults.forEach(({ resource, route }) => {
          const coordinates = resource.currentCoordinates ?? resource.sourceCoordinates
          const modelUri = resource.modelKey ? RESOURCE_MODELS[resource.modelKey] : undefined
          const routeColor = resourceColor(resource)
          const simulatedDuration = route?.duration ?? 0
          const position = new SampledPositionProperty()
          if (route) {
            route.surfacePoints.forEach((routePoint, index, routePoints) => {
              const progress = routePoints.length > 1 ? index / (routePoints.length - 1) : 0
              position.addSample(
                JulianDate.addSeconds(startTime, simulatedDuration * progress, new JulianDate()),
                Cartesian3.fromDegrees(
                  routePoint.longitude,
                  routePoint.latitude,
                  routePoint.vehicleHeight,
                ),
              )
            })
            position.forwardExtrapolationType = ExtrapolationType.HOLD
          }
          const entityId = `${resource.mode}-resource-${resource.id}`
          const entity = route ? viewer?.entities.add({
            id: entityId,
            name: resource.displayName,
            position,
            orientation: createResourceOrientation(position, resource.modelKey),
            viewFrom: new Cartesian3(-190, 0, 125),
            model: modelUri ? {
              uri: modelUri,
              scale: 1.35,
              minimumPixelSize: 72,
              maximumScale: 180,
              distanceDisplayCondition: new DistanceDisplayCondition(0, 40_000),
              silhouetteColor: routeColor,
              silhouetteSize: 2.25,
            } : undefined,
            point: modelUri ? undefined : {
              color: Color.CYAN,
              outlineColor: Color.WHITE,
              outlineWidth: 2,
              pixelSize: 14,
            },
          }) : undefined

          viewer?.entities.add({
            id: `${resource.mode}-resource-origin-${resource.id}`,
            name: `${resource.sourceFacility} · response origin`,
            position: Cartesian3.fromDegrees(
              resource.sourceCoordinates.longitude,
              resource.sourceCoordinates.latitude,
              resource.sourceCoordinates.heightMeters ?? 8,
            ),
            point: {
              color: routeColor,
              outlineColor: Color.WHITE,
              outlineWidth: 3,
              pixelSize: 16,
              scaleByDistance: new NearFarScalar(300, 1.15, 50_000, 0.55),
            },
            label: {
              text: resource.modelKey ? RESOURCE_ORIGIN_SYMBOLS[resource.modelKey] : 'R',
              font: 'bold 11px sans-serif',
              fillColor: Color.WHITE,
              outlineColor: Color.BLACK,
              outlineWidth: 2,
              pixelOffset: new Cartesian2(0, -22),
              style: LabelStyle.FILL_AND_OUTLINE,
              distanceDisplayCondition: new DistanceDisplayCondition(0, 50_000),
              showBackground: true,
              backgroundColor: routeColor.withAlpha(0.8),
              backgroundPadding: new Cartesian2(4, 3),
            },
          })

          viewer?.entities.add({
            id: `${resource.mode}-resource-follow-halo-${resource.id}`,
            position: route ? position : Cartesian3.fromDegrees(
              coordinates.longitude,
              coordinates.latitude,
              coordinates.heightMeters ?? 8,
            ),
            show: false,
            point: {
              color: routeColor.withAlpha(0.08),
              outlineColor: Color.WHITE.withAlpha(0.7),
              outlineWidth: 2,
              pixelSize: 25,
            },
          })

          if (entity && route) {
            viewer?.entities.add({
              id: `${resource.mode}-resource-route-${resource.id}`,
              polyline: {
                positions: route.surfacePoints.map((routePoint) => Cartesian3.fromDegrees(
                  routePoint.longitude,
                  routePoint.latitude,
                  routePoint.routeHeight,
                )),
                width: 5,
                material: new PolylineGlowMaterialProperty({
                  color: routeColor.withAlpha(0.78),
                  glowPower: 0.08,
                  taperPower: 0.65,
                }),
                depthFailMaterial: routeColor.withAlpha(0.62),
              },
            })
            routedAnimations.push({ resource, entityId, route, simulatedDuration })
          }
        })

        if (routedAnimations.length > 0) {
          const stopTime = JulianDate.addSeconds(
            startTime,
            Math.max(...routedAnimations.map(({ simulatedDuration }) => simulatedDuration)),
            new JulianDate(),
          )
          viewer.clock.startTime = startTime.clone()
          viewer.clock.currentTime = startTime.clone()
          viewer.clock.stopTime = stopTime
          viewer.clock.clockRange = ClockRange.CLAMPED
          viewer.clock.multiplier = simulationSpeedRef.current
          viewer.clock.shouldAnimate = true
          const activeViewer = viewer
          let lastSummaryUpdate = 0
          viewer.clock.onTick.addEventListener((clock) => {
            const followedId = followedResourceIdRef.current
            if (followedId) {
              const animation = routedAnimations.find((item) => item.resource.id === followedId)
              const followedEntity = animation
                ? activeViewer.entities.getById(animation.entityId)
                : undefined
              const target = followedEntity?.position?.getValue(clock.currentTime)
              if (target && animation) {
                const lookAheadTime = JulianDate.addSeconds(
                  clock.currentTime,
                  5,
                  new JulianDate(),
                )
                const routeAhead = followedEntity?.position?.getValue(lookAheadTime)
                const desiredHeading = routeAhead && Cartesian3.distance(target, routeAhead) > 0.5
                  ? routeBearing(target, routeAhead)
                  : followHeadingRef.current ?? activeViewer.camera.heading
                const previousHeading = followHeadingRef.current ?? desiredHeading
                const headingDelta = CesiumMath.negativePiToPi(desiredHeading - previousHeading)
                const smoothHeading = previousHeading + headingDelta * FOLLOW_SMOOTHING
                followHeadingRef.current = smoothHeading
                const localFrame = Transforms.eastNorthUpToFixedFrame(target)
                const eastComponent = Math.sin(smoothHeading)
                const northComponent = Math.cos(smoothHeading)
                const desiredCameraPosition = Matrix4.multiplyByPoint(
                  localFrame,
                  new Cartesian3(
                    -eastComponent * FOLLOW_BEHIND_METERS,
                    -northComponent * FOLLOW_BEHIND_METERS,
                    FOLLOW_ABOVE_METERS,
                  ),
                  new Cartesian3(),
                )
                const desiredLookTarget = Matrix4.multiplyByPoint(
                  localFrame,
                  new Cartesian3(
                    eastComponent * FOLLOW_LOOK_AHEAD_METERS,
                    northComponent * FOLLOW_LOOK_AHEAD_METERS,
                    8,
                  ),
                  new Cartesian3(),
                )
                const cameraPosition = followCameraPositionRef.current
                  ? Cartesian3.lerp(
                    followCameraPositionRef.current,
                    desiredCameraPosition,
                    FOLLOW_SMOOTHING,
                    new Cartesian3(),
                  )
                  : desiredCameraPosition
                const lookTarget = followTargetRef.current
                  ? Cartesian3.lerp(
                    followTargetRef.current,
                    desiredLookTarget,
                    FOLLOW_SMOOTHING,
                    new Cartesian3(),
                  )
                  : desiredLookTarget
                followCameraPositionRef.current = Cartesian3.clone(cameraPosition)
                followTargetRef.current = Cartesian3.clone(lookTarget)
                const direction = Cartesian3.normalize(
                  Cartesian3.subtract(lookTarget, cameraPosition, new Cartesian3()),
                  new Cartesian3(),
                )
                const up = Cartesian3.normalize(
                  Matrix4.multiplyByPointAsVector(localFrame, Cartesian3.UNIT_Z, new Cartesian3()),
                  new Cartesian3(),
                )
                activeViewer.camera.setView({
                  destination: cameraPosition,
                  orientation: { direction, up },
                })

                const projectedPosition = SceneTransforms.worldToWindowCoordinates(
                  activeViewer.scene,
                  target,
                  new Cartesian2(),
                )
                const canvas = activeViewer.scene.canvas
                const insideViewport = Boolean(
                  projectedPosition &&
                  projectedPosition.x >= canvas.clientWidth * 0.25 &&
                  projectedPosition.x <= canvas.clientWidth * 0.75 &&
                  projectedPosition.y >= canvas.clientHeight * 0.3 &&
                  projectedPosition.y <= canvas.clientHeight * 0.8,
                )

                if (!insideViewport) {
                  const vehicleTarget = Matrix4.multiplyByPoint(
                    localFrame,
                    new Cartesian3(0, 0, 8),
                    new Cartesian3(),
                  )
                  followTargetRef.current = Cartesian3.clone(vehicleTarget)
                  activeViewer.camera.setView({
                    destination: cameraPosition,
                    orientation: {
                      direction: Cartesian3.normalize(
                        Cartesian3.subtract(vehicleTarget, cameraPosition, new Cartesian3()),
                        new Cartesian3(),
                      ),
                      up,
                    },
                  })
                }

                if (import.meta.env.DEV && performance.now() - followDiagnosticTimeRef.current > 2_000) {
                  followDiagnosticTimeRef.current = performance.now()
                  const modelUriPresent = Boolean(
                    followedEntity?.model?.uri?.getValue(clock.currentTime),
                  )
                  const elapsedSeconds = Math.max(
                    0,
                    JulianDate.secondsDifference(clock.currentTime, startTime),
                  )
                  const routeProgress = Math.min(
                    1,
                    elapsedSeconds / Math.max(animation.simulatedDuration, 1),
                  )
                  const routePointIndex = Math.min(
                    animation.route.surfacePoints.length - 1,
                    Math.round(routeProgress * (animation.route.surfacePoints.length - 1)),
                  )
                  const routePoint = animation.route.surfacePoints[routePointIndex]
                  const currentCartographic = Cartographic.fromCartesian(target)
                  console.debug('[Incident3DView] follow visibility', {
                    worldPositionExists: true,
                    animationPositionValid: Cartesian3.equals(target, Cartesian3.ZERO) === false,
                    entityShow: followedEntity?.show ?? false,
                    modelUriPresent,
                    routePosition: {
                      longitude: Number(CesiumMath.toDegrees(currentCartographic.longitude).toFixed(6)),
                      latitude: Number(CesiumMath.toDegrees(currentCartographic.latitude).toFixed(6)),
                    },
                    currentEllipsoidHeightMeters: Number(currentCartographic.height.toFixed(2)),
                    sampledSurfaceHeightMeters: Number(routePoint.surfaceHeight.toFixed(2)),
                    finalVehicleHeightMeters: Number(routePoint.vehicleHeight.toFixed(2)),
                    surfaceClearanceMeters: Number(
                      (routePoint.vehicleHeight - routePoint.surfaceHeight).toFixed(2),
                    ),
                    surfaceHeightSource: routePoint.heightSource,
                    projectedScreenPosition: projectedPosition
                      ? { x: Math.round(projectedPosition.x), y: Math.round(projectedPosition.y) }
                      : null,
                    insideViewport,
                  })
                }
              }
            }

            const elapsedWall = performance.now()
            if (elapsedWall - lastSummaryUpdate < 500) return
            lastSummaryUpdate = elapsedWall
            setSimulationSummaries(routeResults.map(({ resource, route }) => {
              if (!route) return {
                id: resource.id,
                displayName: resource.displayName,
                sourceFacility: resource.sourceFacility,
                mode: resource.mode,
                status: 'ROUTE UNAVAILABLE' as const,
              }
              const animation = routedAnimations.find((item) => item.resource.id === resource.id)
              const elapsed = Math.max(0, JulianDate.secondsDifference(clock.currentTime, startTime))
              const progress = Math.min(1, elapsed / (animation?.simulatedDuration ?? 1))
              return {
                id: resource.id,
                displayName: resource.displayName,
                sourceFacility: resource.sourceFacility,
                mode: resource.mode,
                routeDistanceKm: route.distance / 1000,
                estimatedDurationSeconds: route.duration,
                remainingDistanceKm: route.distance * (1 - progress) / 1000,
                remainingSeconds: route.duration * (1 - progress),
                simulationRemainingSeconds:
                  route.duration * (1 - progress) / simulationSpeedRef.current,
                status: progress >= 1 ? 'ON SCENE' as const : 'EN ROUTE' as const,
              }
            }))

          })
        }

        initializationStage = 'Camera positioning'
        if (preparedFloodSurface) {
          const heading = routeBearing(
            preparedFloodSurface.origin,
            preparedFloodSurface.downstreamPoint,
          )
          const localFrame = Transforms.eastNorthUpToFixedFrame(preparedFloodSurface.origin)
          const east = Math.sin(heading)
          const north = Math.cos(heading)
          const destination = Matrix4.multiplyByPoint(
            localFrame,
            new Cartesian3(-east * 225, -north * 225, 140),
            new Cartesian3(),
          )
          const target = Matrix4.multiplyByPoint(
            localFrame,
            new Cartesian3(east * 235, north * 235, 5),
            new Cartesian3(),
          )
          viewer.camera.flyTo({
            destination,
            orientation: {
              direction: Cartesian3.normalize(
                Cartesian3.subtract(target, destination, new Cartesian3()),
                new Cartesian3(),
              ),
              up: Cartesian3.normalize(
                Matrix4.multiplyByPointAsVector(
                  localFrame,
                  Cartesian3.UNIT_Z,
                  new Cartesian3(),
                ),
                new Cartesian3(),
              ),
            },
            duration: 0,
          })
        } else {
          viewer.camera.flyTo({
            destination: Cartesian3.fromDegrees(
              sceneIncident.longitude,
              sceneIncident.latitude,
              3_000,
            ),
            orientation: {
              heading: 0,
              pitch: CesiumMath.toRadians(-45),
              roll: 0,
            },
            duration: 0,
          })
        }
        setSceneState('ready')
      } catch (error: unknown) {
        if (isCurrentGeneration()) {
          const sanitizedError = sanitizeInitializationError(error, initializationStage, token)
          setSceneState('error')
          setSceneError(sanitizedError)
          if (import.meta.env.DEV) {
            console.error('[Incident3DView] initialization failed', {
              generation,
              ...sanitizedError,
            })
          }
        } else {
          logLifecycle('stale initialization failure ignored')
        }
      }
    }

    void initialize()

    return () => {
      cancelled = true
      if (initializationGenerationRef.current === generation) {
        initializationGenerationRef.current += 1
      }
      if (tilesetRequestRef.current?.generation === generation) {
        tilesetRequestRef.current = null
      }
      logLifecycle('cleanup')
      cancelAnimationFrame(floodOrbitFrameRef.current)
      floodOrbitFrameRef.current = 0
      viewerRef.current = null
      if (floodRendererRef.current === floodRenderer) floodRendererRef.current = null
      preparedFloodStatesRef.current = []
      if (viewer && !viewer.isDestroyed()) {
        floodRenderer?.destroy()
        viewer.destroy()
        logLifecycle('viewer destroyed')
      }
    }
  }, [
    activeResources,
    exposureAssessments,
    floodVisualization,
    floodStates,
    hasWebGl,
    incident,
    infrastructure,
    isFloodMode,
    retryRequestId,
    riskArea,
    sceneIncident,
    token,
  ])

  useEffect(() => {
    if (!isFloodMode || !isFloodPlaying || sceneState !== 'ready' || floodMaxMinutes <= 0) {
      return
    }

    let animationFrame = 0
    let previousTimestamp: number | null = null
    let lastUiUpdate = 0
    const scenarioMinutesPerSecond = floodMaxMinutes / FLOOD_PLAYBACK_DURATION_SECONDS
    const advance = (timestamp: number) => {
      if (previousTimestamp === null) previousTimestamp = timestamp
      const elapsedSeconds = Math.min(0.1, (timestamp - previousTimestamp) / 1_000)
      previousTimestamp = timestamp
      const nextTime = Math.min(
        floodMaxMinutes,
        floodTimeRef.current + elapsedSeconds * scenarioMinutesPerSecond,
      )
      floodTimeRef.current = nextTime
      floodRendererRef.current?.setTimeMinutes(nextTime)
      if (viewerRef.current) {
        setExposureMarkerVisibility(viewerRef.current, exposureAssessments, nextTime)
      }

      if (timestamp - lastUiUpdate >= 80 || nextTime >= floodMaxMinutes) {
        lastUiUpdate = timestamp
        setFloodTimeMinutes(nextTime)
      }
      if (nextTime >= floodMaxMinutes) {
        setIsFloodPlaying(false)
        return
      }
      animationFrame = requestAnimationFrame(advance)
    }
    animationFrame = requestAnimationFrame(advance)
    return () => cancelAnimationFrame(animationFrame)
  }, [exposureAssessments, floodMaxMinutes, isFloodMode, isFloodPlaying, sceneState])

  useEffect(() => {
    if (!isFloodOrbiting || !isFloodMode || sceneState !== 'ready') return
    const viewer = viewerRef.current
    if (!viewer || viewer.isDestroyed()) return

    let previousTimestamp: number | null = null
    const stopFromManualInteraction = () => {
      cancelAnimationFrame(floodOrbitFrameRef.current)
      floodOrbitFrameRef.current = 0
      if (!viewer.isDestroyed()) viewer.camera.lookAtTransform(Matrix4.IDENTITY)
      setIsFloodOrbiting(false)
    }
    const orbit = (timestamp: number) => {
      if (previousTimestamp === null) previousTimestamp = timestamp
      const elapsedSeconds = Math.min(0.1, (timestamp - previousTimestamp) / 1_000)
      previousTimestamp = timestamp
      viewer.camera.rotateRight(elapsedSeconds * 0.055)
      floodOrbitFrameRef.current = requestAnimationFrame(orbit)
    }
    const canvas = viewer.scene.canvas
    canvas.addEventListener('pointerdown', stopFromManualInteraction)
    canvas.addEventListener('wheel', stopFromManualInteraction, { passive: true })
    canvas.addEventListener('touchstart', stopFromManualInteraction, { passive: true })
    floodOrbitFrameRef.current = requestAnimationFrame(orbit)

    return () => {
      cancelAnimationFrame(floodOrbitFrameRef.current)
      floodOrbitFrameRef.current = 0
      canvas.removeEventListener('pointerdown', stopFromManualInteraction)
      canvas.removeEventListener('wheel', stopFromManualInteraction)
      canvas.removeEventListener('touchstart', stopFromManualInteraction)
    }
  }, [isFloodMode, isFloodOrbiting, sceneState])

  const selectFloodTime = (minutesFromNow: number) => {
    const resolvedTime = Math.min(floodMaxMinutes, Math.max(0, minutesFromNow))
    floodTimeRef.current = resolvedTime
    floodRendererRef.current?.setTimeMinutes(resolvedTime)
    if (viewerRef.current) {
      setExposureMarkerVisibility(viewerRef.current, exposureAssessments, resolvedTime)
    }
    setFloodTimeMinutes(resolvedTime)
  }

  const selectAdjacentFloodState = (direction: -1 | 1) => {
    setIsFloodPlaying(false)
    const nextState = direction < 0
      ? [...floodStates].reverse().find(
          (state) => state.minutesFromNow < floodTimeRef.current - 0.5,
        ) ?? floodStates[0]
      : floodStates.find(
          (state) => state.minutesFromNow > floodTimeRef.current + 0.5,
        ) ?? floodStates.at(-1)
    if (nextState) selectFloodTime(nextState.minutesFromNow)
  }

  const clearFollowMode = (viewer: Viewer) => {
    followedResourceIdRef.current = null
    followHeadingRef.current = null
    followCameraPositionRef.current = null
    followTargetRef.current = null
    viewer.trackedEntity = undefined
    viewer.camera.lookAtTransform(Matrix4.IDENTITY)
    viewer.entities.values
      .filter((entity) => entity.id.includes('-resource-follow-halo-'))
      .forEach((entity) => { entity.show = false })
    viewer.entities.values
      .filter((entity) => entity.id.includes('-resource-') && entity.model)
      .forEach((entity) => {
        if (entity.model) entity.model.minimumPixelSize = new ConstantProperty(72)
      })
    setFollowedResourceId(null)
  }

  const stopFloodOrbit = () => {
    cancelAnimationFrame(floodOrbitFrameRef.current)
    floodOrbitFrameRef.current = 0
    const viewer = viewerRef.current
    if (viewer && !viewer.isDestroyed()) viewer.camera.lookAtTransform(Matrix4.IDENTITY)
    setIsFloodOrbiting(false)
  }

  const focusIncident = (pitchDegrees: number, height: number) => {
    stopFloodOrbit()
    if (viewerRef.current) {
      clearFollowMode(viewerRef.current)
    }
    viewerRef.current?.camera.flyTo({
      destination: Cartesian3.fromDegrees(
        sceneIncident.longitude,
        sceneIncident.latitude,
        height,
      ),
      orientation: { heading: 0, pitch: CesiumMath.toRadians(pitchDegrees), roll: 0 },
      duration: 1,
    })
  }

  const zoomCamera = (factor: number) => {
    const viewer = viewerRef.current
    if (!viewer) return
    stopFloodOrbit()
    clearFollowMode(viewer)
    const position = viewer.camera.positionCartographic
    const height = Math.min(50_000, Math.max(150, position.height * factor))
    viewer.camera.flyTo({
      destination: Cartesian3.fromRadians(position.longitude, position.latitude, height),
      orientation: {
        heading: viewer.camera.heading,
        pitch: viewer.camera.pitch,
        roll: viewer.camera.roll,
      },
      duration: 0.55,
    })
  }

  const resetNorth = () => {
    const viewer = viewerRef.current
    if (!viewer) return
    stopFloodOrbit()
    clearFollowMode(viewer)
    viewer.camera.flyTo({
      destination: viewer.camera.position,
      orientation: { heading: 0, pitch: viewer.camera.pitch, roll: 0 },
      duration: 0.7,
    })
  }

  const fitOperationalArea = () => {
    const viewer = viewerRef.current
    if (!viewer) return
    stopFloodOrbit()
    clearFollowMode(viewer)
    const points = [
      Cartesian3.fromDegrees(sceneIncident.longitude, sceneIncident.latitude),
      ...infrastructure.map((marker) => Cartesian3.fromDegrees(marker.longitude, marker.latitude)),
    ]
    viewer.camera.flyToBoundingSphere(BoundingSphere.fromPoints(points), {
      offset: new HeadingPitchRange(0, CesiumMath.toRadians(-45), 0),
      duration: 1,
    })
  }

  const activeFloodSurfaces = () => {
    const states = preparedFloodStatesRef.current
    if (states.length === 0) return []
    const upperIndex = states.findIndex(
      (state) => state.minutesFromNow >= floodTimeRef.current,
    )
    const resolvedUpperIndex = upperIndex < 0 ? states.length - 1 : upperIndex
    const lowerIndex = Math.max(0, resolvedUpperIndex -
      (states[resolvedUpperIndex].minutesFromNow > floodTimeRef.current ? 1 : 0))
    return lowerIndex === resolvedUpperIndex
      ? [states[lowerIndex].surface]
      : [states[lowerIndex].surface, states[resolvedUpperIndex].surface]
  }

  const activeFloodBoundingSphere = () => {
    const points = activeFloodSurfaces().flatMap((surface) => [
      ...surface.waterHierarchies.flatMap((hierarchy) => hierarchy.positions),
      ...surface.flowPaths.flat(),
    ])
    return points.length > 0 ? BoundingSphere.fromPoints(points) : null
  }

  const representativeFloodSurface = () => {
    const states = preparedFloodStatesRef.current
    return states.reduce<PreparedFloodTimelineState | null>((closest, state) =>
      !closest || Math.abs(state.minutesFromNow - floodTimeRef.current) <
        Math.abs(closest.minutesFromNow - floodTimeRef.current)
        ? state
        : closest, null)?.surface ?? null
  }

  const flyFloodCorridor = (useInitialSurface = false) => {
    const viewer = viewerRef.current
    const surface = useInitialSurface
      ? preparedFloodStatesRef.current[0]?.surface ?? null
      : representativeFloodSurface()
    if (!viewer || !surface) return
    stopFloodOrbit()
    clearFollowMode(viewer)
    const heading = routeBearing(surface.origin, surface.downstreamPoint)
    const localFrame = Transforms.eastNorthUpToFixedFrame(surface.origin)
    const east = Math.sin(heading)
    const north = Math.cos(heading)
    const destination = Matrix4.multiplyByPoint(
      localFrame,
      new Cartesian3(-east * 225, -north * 225, 140),
      new Cartesian3(),
    )
    const target = Matrix4.multiplyByPoint(
      localFrame,
      new Cartesian3(east * 235, north * 235, 5),
      new Cartesian3(),
    )
    viewer.camera.flyTo({
      destination,
      orientation: {
        direction: Cartesian3.normalize(
          Cartesian3.subtract(target, destination, new Cartesian3()),
          new Cartesian3(),
        ),
        up: Cartesian3.normalize(
          Matrix4.multiplyByPointAsVector(localFrame, Cartesian3.UNIT_Z, new Cartesian3()),
          new Cartesian3(),
        ),
      },
      duration: 1,
    })
  }

  const flyToFloodExtent = (pitchDegrees: number, rangeFactor: number) => {
    const viewer = viewerRef.current
    const sphere = activeFloodBoundingSphere()
    const surface = representativeFloodSurface()
    if (!viewer || !sphere || !surface) return
    stopFloodOrbit()
    clearFollowMode(viewer)
    viewer.camera.flyToBoundingSphere(sphere, {
      offset: new HeadingPitchRange(
        routeBearing(surface.origin, surface.downstreamPoint),
        CesiumMath.toRadians(pitchDegrees),
        Math.max(350, sphere.radius * rangeFactor),
      ),
      duration: 1,
    })
  }

  const startFloodOrbit = () => {
    const viewer = viewerRef.current
    const sphere = activeFloodBoundingSphere()
    const surface = representativeFloodSurface()
    if (!viewer || !sphere || !surface) return
    stopFloodOrbit()
    clearFollowMode(viewer)
    viewer.camera.lookAt(
      sphere.center,
      new HeadingPitchRange(
        routeBearing(surface.origin, surface.downstreamPoint),
        CesiumMath.toRadians(-38),
        Math.max(500, sphere.radius * 2.4),
      ),
    )
    setIsFloodOrbiting(true)
  }

  const followResource = (summary: SimulationSummary) => {
    const viewer = viewerRef.current
    if (!viewer) return
    const entity = viewer.entities.getById(`${summary.mode}-resource-${summary.id}`)
    if (!entity) return
    viewer.entities.values
      .filter((candidate) => candidate.id.includes('-resource-follow-halo-'))
      .forEach((candidate) => { candidate.show = false })
    const halo = viewer.entities.getById(`${summary.mode}-resource-follow-halo-${summary.id}`)
    if (halo) halo.show = true
    if (entity.model) entity.model.minimumPixelSize = new ConstantProperty(96)
    followedResourceIdRef.current = summary.id
    followHeadingRef.current = null
    followCameraPositionRef.current = Cartesian3.clone(viewer.camera.positionWC)
    followTargetRef.current = null
    setFollowedResourceId(summary.id)
  }

  const stopFollowing = () => {
    if (viewerRef.current) {
      clearFollowMode(viewerRef.current)
    }
  }

  if (!token) {
    return (
      <div className="incident-3d-state" role="status">
        <strong>3D view is not configured</strong>
        <span>Set VITE_CESIUM_ION_TOKEN to connect the Cesium and Google 3D tile services.</span>
      </div>
    )
  }

  if (!hasWebGl) {
    return (
      <div className="incident-3d-state incident-3d-state--error" role="alert">
        <strong>3D view is unavailable</strong>
        <span>This browser or device does not provide the WebGL capability required by Cesium.</span>
      </div>
    )
  }

  return (
    <div className="incident-3d-view">
      <div
        ref={containerRef}
        className="incident-3d-view__canvas"
        aria-label={isFloodMode ? '3D demo flood visualization' : '3D operational incident map'}
      />

      {sceneState === 'loading' && (
        <div className="incident-3d-view__loading" role="status">Loading Cesium and 3D tiles…</div>
      )}
      {sceneState === 'error' && (
        <div className="incident-3d-view__error" role="alert">
          <strong>3D scene unavailable</strong>
          <span>The operational 3D scene could not initialize.</span>
          <button type="button" onClick={() => setRetryRequestId((current) => current + 1)}>
            Retry 3D scene
          </button>
          {import.meta.env.DEV && sceneError && (
            <details>
              <summary>Development diagnostics</summary>
              <code>{sceneError.stage}: {sceneError.name}: {sceneError.message}</code>
            </details>
          )}
        </div>
      )}

      {sceneState === 'ready' && (
        <div className="incident-3d-view__controls" aria-label="3D camera controls">
          {isFloodMode ? (
            <>
              <button type="button" onClick={() => flyFloodCorridor()}>Flood corridor view</button>
              <button type="button" onClick={() => flyToFloodExtent(-90, 2.1)}>Top view</button>
              <button type="button" onClick={() => flyToFloodExtent(-38, 2.35)}>Oblique view</button>
              <button type="button" onClick={() => flyToFloodExtent(-52, 2.15)}>Fit flood extent</button>
              <button type="button" onClick={() => flyFloodCorridor(true)}>Reset flood camera</button>
              <button
                type="button"
                aria-pressed={isFloodOrbiting}
                onClick={isFloodOrbiting ? stopFloodOrbit : startFloodOrbit}
              >
                {isFloodOrbiting ? 'Stop 360 orbit' : 'Orbit / 360 view'}
              </button>
              <button type="button" onClick={() => zoomCamera(0.65)}>Zoom in</button>
              <button type="button" onClick={() => zoomCamera(1.55)}>Zoom out</button>
            </>
          ) : (
            <>
              <button type="button" onClick={() => focusIncident(-45, 3_000)}>Incident focus</button>
              <button type="button" onClick={() => zoomCamera(0.65)}>Zoom in</button>
              <button type="button" onClick={resetNorth}>North reset</button>
              <button type="button" onClick={() => focusIncident(-90, 5_000)}>Top view</button>
              <button type="button" onClick={() => focusIncident(-35, 7_500)}>Oblique view</button>
              <button type="button" onClick={() => zoomCamera(1.55)}>Zoom out</button>
              <button type="button" onClick={fitOperationalArea}>Fit operational area</button>
            </>
          )}
        </div>
      )}

      {sceneState === 'ready' && isFloodMode && floodStates.length > 0 && (
        <section className="incident-3d-view__flood-timeline" aria-label="Demo flood timeline">
          <header>
            <strong>
              {floodTimeMinutes < 0.5
                ? 'CURRENT · DEMO STATE'
                : `FORECAST · ESTIMATED · ${formatFloodTime(floodTimeMinutes)}`}
            </strong>
            <span>Visual transition only · not a hydrological prediction</span>
          </header>
          <div className="incident-3d-view__flood-playback">
            <button
              type="button"
              onClick={() => {
                if (floodTimeRef.current >= floodMaxMinutes) selectFloodTime(0)
                setIsFloodPlaying(true)
              }}
              disabled={isFloodPlaying}
            >
              Play
            </button>
            <button
              type="button"
              onClick={() => setIsFloodPlaying(false)}
              disabled={!isFloodPlaying}
            >
              Pause
            </button>
            <button type="button" onClick={() => selectAdjacentFloodState(-1)}>
              Previous state
            </button>
            <button type="button" onClick={() => selectAdjacentFloodState(1)}>
              Next state
            </button>
            <button
              type="button"
              onClick={() => {
                setIsFloodPlaying(false)
                selectFloodTime(0)
              }}
            >
              Reset to NOW
            </button>
          </div>
          <label>
            <span>Propagation time: {formatFloodTime(floodTimeMinutes)}</span>
            <input
              type="range"
              min={0}
              max={floodMaxMinutes}
              step={1}
              value={floodTimeMinutes}
              onChange={(event) => {
                setIsFloodPlaying(false)
                selectFloodTime(Number(event.target.value))
              }}
            />
          </label>
          <div className="incident-3d-view__flood-state-markers" aria-label="Flood states">
            {floodStates.map((state) => (
              <button
                key={state.minutesFromNow}
                type="button"
                aria-current={Math.abs(floodTimeMinutes - state.minutesFromNow) < 0.5
                  ? 'step'
                  : undefined}
                onClick={() => {
                  setIsFloodPlaying(false)
                  selectFloodTime(state.minutesFromNow)
                }}
              >
                {formatFloodTime(state.minutesFromNow)}
              </button>
            ))}
          </div>
          <details className="incident-3d-view__flood-exposure">
            <summary>
              Infrastructure exposure · {exposureAssessments.filter(({ exposure }) =>
                exposure.firstExposedMinutesFromNow !== undefined &&
                floodTimeMinutes >= exposure.firstExposedMinutesFromNow).length} potentially
              exposed at selected state
            </summary>
            <p>Estimated geometry intersection only · no closure, availability, or dispatch status.</p>
            {!exposureAssessments.some(({ source }) => source === 'geospatial-context') && (
              <p>Real nearby infrastructure context is not currently available.</p>
            )}
            <ul>
              {displayedExposureAssessments.map((assessment) => {
                const { exposure } = assessment
                const firstExposure = exposure.firstExposedMinutesFromNow
                const currentlyExposed = firstExposure !== undefined &&
                  floodTimeMinutes >= firstExposure
                return (
                  <li key={`${assessment.source}-${exposure.id}`}>
                    <div>
                      <strong>{exposure.name ?? `Unnamed ${exposure.type}`}</strong>
                      <span>{exposure.type.replaceAll('-', ' ')}</span>
                    </div>
                    <span>
                      {firstExposure === undefined
                        ? 'Not exposed within scenario horizon'
                        : currentlyExposed
                          ? firstExposure === 0
                            ? 'Current demo exposure'
                            : 'Potentially exposed at selected state'
                          : 'Not exposed at selected state'}
                    </span>
                    <small>
                      {firstExposure === undefined
                        ? 'No supplied demo state intersects this location'
                        : `${firstExposure === 0 ? 'Current demo' : 'Forecast · estimated'} exposure: ${formatFloodTime(firstExposure)}`}
                      {' · '}
                      {assessment.assessmentBasis === 'point-in-polygon'
                        ? 'representative point assessment'
                        : assessment.assessmentBasis.replaceAll('-', ' ')}
                      {assessment.source === 'demo-fixture' ? ' · synthetic demo fixture' : ' · OSM/geospatial context'}
                    </small>
                  </li>
                )
              })}
            </ul>
            {exposureAssessments.length > displayedExposureAssessments.length && (
              <small>
                Showing {displayedExposureAssessments.length} of {exposureAssessments.length} nearby items;
                potentially exposed items are listed first.
              </small>
            )}
          </details>
        </section>
      )}

      {sceneState === 'ready' && !isFloodMode && allocatedResources.length === 0 && !demoActive && (
        <div className="incident-3d-view__demo-prompt">
          <strong>Demo Response Simulation</strong>
          <span>Visualization only · no resources are dispatched or allocated.</span>
          <button
            type="button"
            disabled={infrastructure.length === 0}
            onClick={() => setDemoActive(true)}
          >
            Run Demo Simulation
          </button>
        </div>
      )}

      {sceneState === 'ready' && !isFloodMode && simulationSummaries.length > 0 && (
        <section
          className={`incident-3d-view__simulation${isSimulationPanelCollapsed ? ' incident-3d-view__simulation--collapsed' : ''}`}
          aria-label="Response route simulation"
        >
          <header>
            <strong>{simulationSummaries[0].mode === 'demo' ? 'DEMO · NOT DISPATCHED' : 'VERIFIED ALLOCATION'}</strong>
            <div>
              <button
                type="button"
                aria-expanded={!isSimulationPanelCollapsed}
                onClick={() => setIsSimulationPanelCollapsed((collapsed) => !collapsed)}
              >
                {isSimulationPanelCollapsed ? 'Show details' : 'Minimize'}
              </button>
              {simulationSummaries[0].mode === 'demo' && (
                <button type="button" onClick={() => setDemoActive(false)}>Stop demo</button>
              )}
            </div>
          </header>
          {!isSimulationPanelCollapsed && (
            <div className="incident-3d-view__simulation-content">
          <label className="incident-3d-view__speed">
            Simulation speed
            <select
              value={simulationSpeed}
              onChange={(event) => {
                const speed = Number(event.target.value) as SimulationSpeed
                simulationSpeedRef.current = speed
                setSimulationSpeed(speed)
                if (viewerRef.current) viewerRef.current.clock.multiplier = speed
              }}
            >
              <option value={1}>1x Real time</option>
              <option value={2}>2x</option>
              <option value={4}>4x</option>
              <option value={8}>8x Demo</option>
            </select>
          </label>
          {simulationSummaries.map((summary) => (
            <article key={summary.id}>
              <div><strong>{summary.displayName}</strong><span>{summary.sourceFacility}</span></div>
              <dl>
                <div><dt>Status</dt><dd>{summary.status}</dd></div>
                <div><dt>Route estimate</dt><dd>{summary.routeDistanceKm === undefined ? 'Unavailable' : `${summary.routeDistanceKm.toFixed(1)} km`}</dd></div>
                <div><dt>Estimated real travel time</dt><dd>{formatDuration(summary.estimatedDurationSeconds)}</dd></div>
                <div><dt>Remaining route</dt><dd>{summary.remainingDistanceKm === undefined ? 'Unavailable' : `${summary.remainingDistanceKm.toFixed(1)} km · ${formatDuration(summary.remainingSeconds)}`}</dd></div>
                <div><dt>Simulation arrival</dt><dd>{formatDuration(summary.simulationRemainingSeconds)}</dd></div>
              </dl>
              {summary.status !== 'ROUTE UNAVAILABLE' && (
                <button type="button" onClick={() => followResource(summary)}>
                  {followedResourceId === summary.id ? 'Following vehicle' : 'Follow vehicle'}
                </button>
              )}
            </article>
          ))}
          {followedResourceId && <button type="button" onClick={stopFollowing}>Return to free camera</button>}
            </div>
          )}
        </section>
      )}

      <div className="incident-3d-view__semantics">
        <span><i className="incident-3d-view__dot incident-3d-view__dot--incident" />Incident location</span>
        {isFloodMode && (
          <>
            <span><i className="incident-3d-view__swatch incident-3d-view__swatch--flood" />Animated flood water</span>
            <span><i className="incident-3d-view__line incident-3d-view__line--flow" />Estimated flow direction</span>
          </>
        )}
        <span><i className="incident-3d-view__dot incident-3d-view__dot--context" />Nearby infrastructure</span>
        {!isFloodMode && (
          <span><i className="incident-3d-view__dot incident-3d-view__dot--allocated" />Verified allocation</span>
        )}
      </div>

      <div className="incident-3d-view__notices" aria-live="polite">
        {isFloodMode && (
          <strong>DEMO · ESTIMATED FLOOD PROPAGATION · NOT OPERATIONAL</strong>
        )}
        {infrastructure.length === 0 && <span>No nearby infrastructure is available to display.</span>}
        {!isFloodMode && allocatedResources.length === 0 && <span>No verified allocated resources.</span>}
      </div>
    </div>
  )
}

export default Incident3DView
