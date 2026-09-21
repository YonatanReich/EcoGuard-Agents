import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useMap } from 'react-map-gl/mapbox'
import mapboxgl, { type CustomLayerInterface, type Map as MapboxMap } from 'mapbox-gl'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import type { AllocationVehicle } from '../../utils/resourceAllocationSimulation'

const LAYER_ID = 'allocation-vehicle-three-layer'
const EARTH_RADIUS_METERS = 6_371_000
const EARTH_CIRCUMFERENCE_METERS = 2 * Math.PI * EARTH_RADIUS_METERS
const REFERENCE_ZOOM = 15
const MIN_ZOOM_MULTIPLIER = 0.125
const MAX_ZOOM_MULTIPLIER = 16
const ROAD_CLEARANCE_METERS = 0.25
const TARGET_MODEL_PIXELS: Record<AllocationVehicle['vehicleType'], number> = {
  'fire-truck': 36,
  ambulance: 31,
  'police-car': 27,
}

type Playback = { elapsedSeconds: number; startedAt: number; running: boolean }
type VehicleFrame = { vehicle: AllocationVehicle; longitude: number; latitude: number; bearing: number; progress: number }

function radians(value: number) { return value * Math.PI / 180 }
function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value))
}

function referenceMetersPerPixel(latitude: number) {
  return Math.cos(radians(latitude)) * EARTH_CIRCUMFERENCE_METERS / (512 * 2 ** REFERENCE_ZOOM)
}

function segmentMeters([leftLongitude, leftLatitude]: [number, number], [rightLongitude, rightLatitude]: [number, number]) {
  const latitudeDelta = radians(rightLatitude - leftLatitude)
  const longitudeDelta = radians(rightLongitude - leftLongitude)
  const leftLatitudeRadians = radians(leftLatitude)
  const rightLatitudeRadians = radians(rightLatitude)
  const haversine = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(leftLatitudeRadians) * Math.cos(rightLatitudeRadians) * Math.sin(longitudeDelta / 2) ** 2
  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.sqrt(haversine))
}

function bearing(startLongitude: number, startLatitude: number, endLongitude: number, endLatitude: number) {
  const longitudeDelta = radians(endLongitude - startLongitude)
  const startLatitudeRadians = radians(startLatitude)
  const endLatitudeRadians = radians(endLatitude)
  const y = Math.sin(longitudeDelta) * Math.cos(endLatitudeRadians)
  const x = Math.cos(startLatitudeRadians) * Math.sin(endLatitudeRadians)
    - Math.sin(startLatitudeRadians) * Math.cos(endLatitudeRadians) * Math.cos(longitudeDelta)
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360
}

function routeFrame(vehicle: AllocationVehicle, progress: number): VehicleFrame {
  const coordinates = vehicle.route.coordinates
  if (progress <= 0) {
    const [nextLongitude, nextLatitude] = coordinates[1]
    return { vehicle, longitude: vehicle.origin.longitude, latitude: vehicle.origin.latitude,
      bearing: bearing(vehicle.origin.longitude, vehicle.origin.latitude, nextLongitude, nextLatitude), progress: 0 }
  }
  const lengths = coordinates.slice(1).map((coordinate, index) => segmentMeters(coordinates[index], coordinate))
  const totalLength = lengths.reduce((sum, length) => sum + length, 0)
  const target = totalLength * Math.min(1, progress)
  let travelled = 0
  for (let index = 0; index < lengths.length; index += 1) {
    const nextTravelled = travelled + lengths[index]
    if (target <= nextTravelled || index === lengths.length - 1) {
      const fraction = lengths[index] > 0 ? (target - travelled) / lengths[index] : 0
      const [startLongitude, startLatitude] = coordinates[index]
      const [endLongitude, endLatitude] = coordinates[index + 1]
      return { vehicle,
        longitude: startLongitude + (endLongitude - startLongitude) * fraction,
        latitude: startLatitude + (endLatitude - startLatitude) * fraction,
        bearing: bearing(startLongitude, startLatitude, endLongitude, endLatitude), progress: Math.min(1, progress) }
    }
    travelled = nextTravelled
  }
  const [longitude, latitude] = coordinates[coordinates.length - 1]
  return { vehicle, longitude, latitude, bearing: 0, progress: 1 }
}

type VehicleThreeLayer = CustomLayerInterface & { updateFrames: (frames: VehicleFrame[]) => void }
type ModelLoadPhase = 'waiting' | 'started' | 'ready' | 'error'
type ModelLoadState = { phase: ModelLoadPhase; url: string; error?: string }

function loaderErrorMessage(error: unknown, url: string) {
  if (error instanceof Error) return error.message
  if (error instanceof ProgressEvent) {
    const request = error.target as XMLHttpRequest | null
    if (request) return `${request.status || 'network'} ${request.statusText || 'error'} at ${request.responseURL || url}`
  }
  return `Unknown GLTFLoader error at ${url}`
}

function createVehicleThreeLayer(
  vehicles: AllocationVehicle[],
  initialFrames: VehicleFrame[],
  onLayerActive: () => void,
  onLayerError: (error: string) => void,
  onModelStatus: (vehicleId: string, phase: ModelLoadPhase, error?: string) => void,
): VehicleThreeLayer {
  let map: MapboxMap | null = null
  let renderer: THREE.WebGLRenderer | null = null
  let frames = initialFrames
  const camera = new THREE.Camera()
  const scene = new THREE.Scene()
  const models = new Map<string, THREE.Object3D>()
  const loadTimeouts = new Map<string, number>()
  let renderErrorReported = false

  scene.add(new THREE.AmbientLight(0xffffff, 2.5))
  const directionalLight = new THREE.DirectionalLight(0xffffff, 3)
  directionalLight.position.set(0, -70, 100)
  scene.add(directionalLight)

  const updateTransforms = () => {
    if (!map) return
    for (const frame of frames) {
      const model = models.get(frame.vehicle.id)
      if (!model) continue
      const terrainElevation = map.queryTerrainElevation(
        [frame.longitude, frame.latitude],
        { exaggerated: true },
      ) ?? 0
      const coordinate = mapboxgl.MercatorCoordinate.fromLngLat(
        [frame.longitude, frame.latitude],
        terrainElevation + ROAD_CLEARANCE_METERS,
      )
      const zoomMultiplier = clamp(
        2 ** (REFERENCE_ZOOM - map.getZoom()),
        MIN_ZOOM_MULTIPLIER,
        MAX_ZOOM_MULTIPLIER,
      )
      const targetLengthMeters = TARGET_MODEL_PIXELS[frame.vehicle.vehicleType]
        * referenceMetersPerPixel(frame.latitude)
        * zoomMultiplier
      const scale = coordinate.meterInMercatorCoordinateUnits() * targetLengthMeters
      const transform = new THREE.Matrix4()
        .makeTranslation(coordinate.x, coordinate.y, coordinate.z)
        .multiply(new THREE.Matrix4().makeRotationZ(
          radians(frame.bearing + frame.vehicle.headingOffset),
        ))
        .scale(new THREE.Vector3(scale, -scale, scale))
        .multiply(new THREE.Matrix4().makeRotationX(Math.PI / 2))
      model.matrixAutoUpdate = false
      model.matrix.copy(transform)
      model.visible = true
    }
  }

  return {
    id: LAYER_ID,
    type: 'custom',
    slot: 'top',
    renderingMode: '3d',
    onAdd(addedMap, gl) {
      onLayerActive()
      console.info('[allocation-3d] custom layer onAdd')
      map = addedMap
      renderer = new THREE.WebGLRenderer({ canvas: addedMap.getCanvas(), context: gl, antialias: true })
      renderer.autoClear = false
      renderer.outputColorSpace = THREE.SRGBColorSpace
      const loader = new GLTFLoader()
      for (const vehicle of vehicles) {
        let settled = false
        console.info(`[allocation-3d] loading started: ${vehicle.modelUrl}`)
        onModelStatus(vehicle.id, 'started')
        const timeout = window.setTimeout(() => {
          if (settled) return
          settled = true
          const message = `Timed out after 20s loading ${vehicle.modelUrl}`
          console.error(`[allocation-3d] ${message}`)
          onModelStatus(vehicle.id, 'error', message)
        }, 20_000)
        loadTimeouts.set(vehicle.id, timeout)
        loader.load(vehicle.modelUrl, (gltf) => {
          if (settled) return
          settled = true
          window.clearTimeout(timeout)
          loadTimeouts.delete(vehicle.id)
          const model = gltf.scene
          model.updateMatrixWorld(true)
          const bounds = new THREE.Box3().setFromObject(model)
          const center = bounds.getCenter(new THREE.Vector3())
          const dimensions = bounds.getSize(new THREE.Vector3())
          const horizontalLength = Math.max(dimensions.x, dimensions.z)
          if (!Number.isFinite(horizontalLength) || horizontalLength <= 0) {
            const message = `Invalid model bounds for ${vehicle.modelUrl}`
            console.error(`[allocation-3d] ${message}`)
            onModelStatus(vehicle.id, 'error', message)
            return
          }
          model.position.x -= center.x
          model.position.y -= bounds.min.y
          model.position.z -= center.z
          model.traverse((object) => {
            object.frustumCulled = false
            if (object instanceof THREE.Mesh) {
              object.castShadow = false
              object.receiveShadow = false
              const materials = Array.isArray(object.material) ? object.material : [object.material]
              for (const material of materials) {
                material.opacity = 1
                material.visible = true
                material.needsUpdate = true
              }
            }
          })
          const positionedModel = new THREE.Group()
          positionedModel.name = vehicle.modelId
          const normalizedModel = new THREE.Group()
          normalizedModel.scale.setScalar(1 / horizontalLength)
          normalizedModel.add(model)
          positionedModel.add(normalizedModel)
          console.info('[allocation-3d] normalized model', {
            vehicle: vehicle.vehicleType,
            sourceDimensions: dimensions.toArray(),
            normalizedHorizontalLength: 1,
            targetPixels: TARGET_MODEL_PIXELS[vehicle.vehicleType],
            headingOffset: vehicle.headingOffset,
          })
          models.set(vehicle.id, positionedModel)
          scene.add(positionedModel)
          updateTransforms()
          console.info(`[allocation-3d] loading succeeded: ${vehicle.modelUrl}`)
          onModelStatus(vehicle.id, 'ready')
          addedMap.triggerRepaint()
        }, undefined, (error) => {
          if (settled) return
          settled = true
          window.clearTimeout(timeout)
          loadTimeouts.delete(vehicle.id)
          const message = loaderErrorMessage(error, vehicle.modelUrl)
          console.error(`[allocation-3d] loading failed: ${vehicle.modelUrl}`, error)
          onModelStatus(vehicle.id, 'error', message)
        })
      }
    },
    render(_gl, matrix) {
      if (!renderer) return
      try {
        updateTransforms()
        camera.projectionMatrix.fromArray(matrix)
        renderer.resetState()
        renderer.render(scene, camera)
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unknown Three.js render error'
        console.error('[allocation-3d] render failed', error)
        if (!renderErrorReported) {
          renderErrorReported = true
          onLayerError(message)
        }
      }
    },
    onRemove() {
      for (const timeout of loadTimeouts.values()) window.clearTimeout(timeout)
      loadTimeouts.clear()
      for (const model of models.values()) scene.remove(model)
      models.clear()
      renderer?.dispose()
      renderer = null
      map = null
    },
    updateFrames(nextFrames) {
      frames = nextFrames
      updateTransforms()
      map?.triggerRepaint()
    },
  }
}

function formatDistance(meters: number) { return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km` }
function formatTime(seconds: number) {
  const rounded = Math.max(0, Math.ceil(seconds))
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}

export default function AllocationVehicleSimulation({ vehicles }: { vehicles: AllocationVehicle[] }) {
  const { current: mapRef } = useMap()
  const layerRef = useRef<VehicleThreeLayer | null>(null)
  const [speed, setSpeed] = useState(8)
  const [now, setNow] = useState(0)
  const [layerActive, setLayerActive] = useState(false)
  // The Three.js layer and its models are only built once Run is pressed.
  // Building them on mount put a renderer, five GLTF parses and a round of
  // shader compiles on every click that selected an event.
  const [armed, setArmed] = useState(false)
  const [layerError, setLayerError] = useState<string | null>(null)
  const [modelStates, setModelStates] = useState<Record<string, ModelLoadState>>(() => Object.fromEntries(
    vehicles.map((vehicle) => [vehicle.id, { phase: 'waiting', url: vehicle.modelUrl }]),
  ))
  const [playback, setPlayback] = useState<Playback>({ elapsedSeconds: 0, startedAt: 0, running: false })
  const longestDuration = useMemo(() => Math.max(...vehicles.map((vehicle) => vehicle.route.durationSeconds)), [vehicles])
  const elapsedSeconds = playback.running
    ? Math.min(longestDuration, playback.elapsedSeconds + (now - playback.startedAt) * speed / 1000) : playback.elapsedSeconds
  const frames = useMemo(() => vehicles.map((vehicle) => routeFrame(vehicle,
    Math.min(1, elapsedSeconds / vehicle.route.durationSeconds))), [elapsedSeconds, vehicles])

  useEffect(() => {
    if (!playback.running) return
    let animationFrame = 0
    const draw = (time: number) => {
      setNow(time)
      if (playback.elapsedSeconds + (time - playback.startedAt) * speed / 1000 >= longestDuration) {
        setPlayback({ elapsedSeconds: longestDuration, startedAt: time, running: false })
        return
      }
      animationFrame = requestAnimationFrame(draw)
    }
    animationFrame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(animationFrame)
  }, [longestDuration, playback, speed])

  useEffect(() => {
    const map = mapRef?.getMap()
    if (!map || !armed) return
    const initialFrames = vehicles.map((vehicle) => routeFrame(vehicle, 0))
    let onAddRan = false
    let registrationInterval = 0
    const layer = createVehicleThreeLayer(
      vehicles,
      initialFrames,
      () => {
        onAddRan = true
        window.clearInterval(registrationInterval)
        setLayerActive(true)
      },
      setLayerError,
      (vehicleId, phase, error) => setModelStates((current) => ({
        ...current,
        [vehicleId]: { ...current[vehicleId], phase, error },
      })),
    )
    layerRef.current = layer
    const setup = () => {
      if (map.getLayer(LAYER_ID)) return
      try {
        map.addLayer(layer)
        if (!map.getLayer(LAYER_ID)) setLayerError('Custom layer did not register.')
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Custom layer registration failed.'
        if (!/style.*load/i.test(message)) setLayerError(message)
      }
    }
    setup()
    if (!onAddRan) registrationInterval = window.setInterval(setup, 250)
    const registrationTimeout = window.setTimeout(() => {
      window.clearInterval(registrationInterval)
      if (!onAddRan) setLayerError('Custom layer onAdd did not execute within 10s.')
    }, 10_000)
    map.on('load', setup)
    map.on('style.load', setup)
    map.on('styledata', setup)
    return () => {
      map.off('load', setup)
      map.off('style.load', setup)
      map.off('styledata', setup)
      window.clearInterval(registrationInterval)
      window.clearTimeout(registrationTimeout)
      if (map.getLayer(LAYER_ID)) map.removeLayer(LAYER_ID)
      layerRef.current = null
    }
  }, [armed, mapRef, vehicles])

  useEffect(() => {
    layerRef.current?.updateFrames(frames)
  }, [frames])

  const rebaseSpeed = useCallback((nextSpeed: number) => {
    const changedAt = performance.now()
    setPlayback((current) => ({ elapsedSeconds: current.running
      ? Math.min(longestDuration, current.elapsedSeconds + (changedAt - current.startedAt) * speed / 1000)
      : current.elapsedSeconds, startedAt: changedAt, running: current.running }))
    setNow(changedAt)
    setSpeed(nextSpeed)
  }, [longestDuration, speed])

  const start = (restart: boolean) => {
    setArmed(true)
    const startedAt = performance.now()
    setNow(startedAt)
    setPlayback((current) => ({ elapsedSeconds: restart || current.elapsedSeconds >= longestDuration ? 0 : current.elapsedSeconds,
      startedAt, running: true }))
    const map = mapRef?.getMap()
    if (map) {
      const coordinates = vehicles.flatMap((vehicle) => vehicle.route.coordinates)
      const longitudes = coordinates.map(([longitude]) => longitude)
      const latitudes = coordinates.map(([, latitude]) => latitude)
      map.fitBounds([[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]],
        { padding: 90, duration: 800, maxZoom: 15.5 })
    }
  }

  const stop = () => {
    const stoppedAt = performance.now()
    setPlayback((current) => ({ elapsedSeconds: current.running
      ? Math.min(longestDuration, current.elapsedSeconds + (stoppedAt - current.startedAt) * speed / 1000)
      : current.elapsedSeconds, startedAt: stoppedAt, running: false }))
    setNow(stoppedAt)
  }

  const readyCount = Object.values(modelStates).filter(({ phase }) => phase === 'ready').length
  const modelError = Object.entries(modelStates).find(([, state]) => state.phase === 'error')
  const modelStatus = layerError
    ? `3D error: ${layerError}`
    : modelError
      ? `3D error: ${modelError[0]} · ${modelError[1].error}`
      : layerActive
        ? `3D: ready ${readyCount}/${vehicles.length}`
        : armed ? '3D: activating' : '3D: loads on Run'

  return <div className="allocation-simulation-panel">
    <div className="allocation-simulation-header">
      <strong>DEMO · NOT DISPATCHED</strong>
      <span className={modelStatus.includes('error') ? 'allocation-simulation-error' : 'allocation-simulation-model-status'} title={modelStatus}>
        {modelStatus.includes('error') ? '3D: error' : modelStatus}
      </span>
    </div>
    {modelStatus.includes('error') && <span className="allocation-simulation-error-detail">{modelStatus}</span>}
    <div className="allocation-simulation-controls">
      <button type="button" disabled={playback.running} onClick={() => start(false)}>Run</button>
      <button type="button" onClick={() => start(true)}>Restart</button>
      <button type="button" disabled={!playback.running} onClick={stop}>Stop</button>
      <label className="allocation-simulation-speed">
        <span>Speed</span>
        <input type="range" min={1} max={8} step={1} value={speed} onChange={(event) => rebaseSpeed(Number(event.target.value))} />
        <output>{speed}×</output>
      </label>
    </div>
    <div className="allocation-simulation-vehicles">
      {frames.map(({ vehicle, progress }) => <div key={vehicle.id}>
        <span className="allocation-vehicle-type" style={{ '--allocation-vehicle-color': vehicle.color } as CSSProperties}>{vehicle.shortLabel}</span>
        <span className="allocation-vehicle-name" title={vehicle.sourceName}>{vehicle.sourceName}</span>
        <span className="allocation-vehicle-remaining">{progress >= 1 ? 'Arrived' : `${formatDistance(vehicle.route.distanceMeters * (1 - progress))} · ${formatTime(vehicle.route.durationSeconds * (1 - progress))}`}</span>
      </div>)}
    </div>
  </div>
}
