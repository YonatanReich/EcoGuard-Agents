import {
  Color,
  GeometryInstance,
  Material,
  MaterialAppearance,
  PolygonGeometry,
  PolylineGeometry,
  PolylineMaterialAppearance,
  Primitive,
  Scene,
} from 'cesium'

import type { PreparedFloodSurface } from './floodSurfaceGeometry'
import {
  createDirectionalFlowMaterial,
  FLOOD_FLOW_ALPHA,
  FLOOD_FRONT_ALPHA,
  FLOOD_WATER_BASE_ALPHA,
  FLOOD_WATER_BLEND_ALPHA,
  createFloodFrontMaterial,
  createFloodWaterMaterial,
} from './floodMaterials'

export type PreparedFloodTimelineState = {
  minutesFromNow: number
  surface: PreparedFloodSurface
}

export type FloodWaterRenderer = {
  setTimeMinutes: (minutesFromNow: number) => void
  destroy: () => void
}

type StatePrimitives = {
  minutesFromNow: number
  waterMaterial: Material
  flowMaterial: Material
  frontMaterial: Material
  waterPrimitive: Primitive
  flowPrimitive: Primitive
  frontPrimitive: Primitive | null
}

function setMaterialAlpha(material: Material, uniform: string, alpha: number) {
  const color = material.uniforms[uniform] as Color
  color.alpha = alpha
}

function createStatePrimitives(
  scene: Scene,
  timelineState: PreparedFloodTimelineState,
): StatePrimitives {
  const { surface } = timelineState
  const waterMaterial = createFloodWaterMaterial()
  const flowMaterial = createDirectionalFlowMaterial()
  const frontMaterial = createFloodFrontMaterial()
  const waterPrimitive = scene.primitives.add(new Primitive({
    geometryInstances: surface.waterHierarchies.map((polygonHierarchy, index) =>
      new GeometryInstance({
        id: `demo-flood-water-${timelineState.minutesFromNow}-${index}`,
        geometry: new PolygonGeometry({
          polygonHierarchy,
          perPositionHeight: true,
          vertexFormat: MaterialAppearance.MaterialSupport.ALL.vertexFormat,
        }),
      })),
    appearance: new MaterialAppearance({
      material: waterMaterial,
      materialSupport: MaterialAppearance.MaterialSupport.ALL,
      translucent: true,
      closed: false,
      faceForward: true,
    }),
    asynchronous: true,
  }))

  const flowPrimitive = scene.primitives.add(new Primitive({
    geometryInstances: surface.flowPaths.map((positions, index) =>
      new GeometryInstance({
        id: `demo-flood-flow-${timelineState.minutesFromNow}-${index}`,
        geometry: new PolylineGeometry({
          positions,
          width: 11,
          vertexFormat: PolylineMaterialAppearance.VERTEX_FORMAT,
        }),
      })),
    appearance: new PolylineMaterialAppearance({ material: flowMaterial, translucent: true }),
    asynchronous: true,
  }))

  const frontInstances = surface.flowPaths.flatMap((positions, index) => {
    const pointCount = Math.min(7, Math.max(3, Math.ceil(positions.length * 0.16)))
    const frontPositions = positions.slice(-pointCount)
    return frontPositions.length < 2 ? [] : [new GeometryInstance({
      id: `demo-flood-front-${timelineState.minutesFromNow}-${index}`,
      geometry: new PolylineGeometry({
        positions: frontPositions,
        width: 17,
        vertexFormat: PolylineMaterialAppearance.VERTEX_FORMAT,
      }),
    })]
  })
  const frontPrimitive = frontInstances.length === 0 ? null : scene.primitives.add(new Primitive({
    geometryInstances: frontInstances,
    appearance: new PolylineMaterialAppearance({ material: frontMaterial, translucent: true }),
    asynchronous: true,
  }))

  return {
    minutesFromNow: timelineState.minutesFromNow,
    waterMaterial,
    flowMaterial,
    frontMaterial,
    waterPrimitive,
    flowPrimitive,
    frontPrimitive,
  }
}

function setStateOpacity(state: StatePrimitives, opacity: number) {
  const visible = opacity > 0.002
  state.waterPrimitive.show = visible
  state.flowPrimitive.show = visible
  if (state.frontPrimitive) state.frontPrimitive.show = visible
  setMaterialAlpha(state.waterMaterial, 'baseWaterColor', FLOOD_WATER_BASE_ALPHA * opacity)
  setMaterialAlpha(state.waterMaterial, 'blendColor', FLOOD_WATER_BLEND_ALPHA * opacity)
  setMaterialAlpha(state.flowMaterial, 'color', FLOOD_FLOW_ALPHA * opacity)
  setMaterialAlpha(state.frontMaterial, 'color', FLOOD_FRONT_ALPHA * opacity)
}

export function attachFloodWaterRenderer(
  scene: Scene,
  timelineStates: readonly PreparedFloodTimelineState[],
): FloodWaterRenderer {
  const states = [...timelineStates]
    .sort((left, right) => left.minutesFromNow - right.minutesFromNow)
    .map((state) => createStatePrimitives(scene, state))

  const setTimeMinutes = (minutesFromNow: number) => {
    if (states.length === 0) return
    const upperIndex = states.findIndex((state) => state.minutesFromNow >= minutesFromNow)
    const resolvedUpperIndex = upperIndex < 0 ? states.length - 1 : upperIndex
    const lowerIndex = Math.max(0, resolvedUpperIndex -
      (states[resolvedUpperIndex].minutesFromNow > minutesFromNow ? 1 : 0))
    const lower = states[lowerIndex]
    const upper = states[resolvedUpperIndex]
    const duration = upper.minutesFromNow - lower.minutesFromNow
    const linearProgress = duration > 0
      ? (minutesFromNow - lower.minutesFromNow) / duration
      : 0
    const progress = linearProgress * linearProgress * (3 - 2 * linearProgress)

    states.forEach((state, index) => {
      const opacity = lowerIndex === resolvedUpperIndex
        ? (index === lowerIndex ? 1 : 0)
        : index === lowerIndex
          ? 1 - progress
          : index === resolvedUpperIndex
            ? progress
            : 0
      setStateOpacity(state, opacity)
    })
  }

  setTimeMinutes(states[0]?.minutesFromNow ?? 0)
  const animationStartedAt = performance.now()
  const updateMaterialTime = () => {
    const elapsedSeconds = (performance.now() - animationStartedAt) / 1_000
    states.forEach((state) => {
      state.flowMaterial.uniforms.time = elapsedSeconds
      state.frontMaterial.uniforms.time = elapsedSeconds
    })
  }
  scene.preRender.addEventListener(updateMaterialTime)

  let destroyed = false
  return {
    setTimeMinutes,
    destroy: () => {
      if (destroyed) return
      destroyed = true
      scene.preRender.removeEventListener(updateMaterialTime)
      states.forEach((state) => {
        if (state.frontPrimitive && scene.primitives.contains(state.frontPrimitive)) {
          scene.primitives.remove(state.frontPrimitive)
        }
        if (scene.primitives.contains(state.flowPrimitive)) {
          scene.primitives.remove(state.flowPrimitive)
        }
        if (scene.primitives.contains(state.waterPrimitive)) {
          scene.primitives.remove(state.waterPrimitive)
        }
      })
    },
  }
}
