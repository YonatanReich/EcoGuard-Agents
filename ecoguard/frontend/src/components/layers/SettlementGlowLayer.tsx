/**
 * SettlementGlowLayer — the settlements the selected event touches, lit up.
 *
 * Red for settlements affected now (a fire already burning in them, towns
 * inside an earthquake's impact area); yellow for those at risk (in a fire's
 * forecast spread, downwind in an air-pollution corridor). A soft blurred edge
 * and a faint fill, so the outline reads without hiding the map beneath.
 * Hovering one shows its name in bold white above it.
 *
 * The outlines come from /api/towns/outlines, fetched once per event.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Layer, Marker, Source, useMap } from 'react-map-gl/mapbox'
import type { ExpressionSpecification, MapLayerMouseEvent } from 'mapbox-gl'
import type { MultiPolygon, Polygon } from 'geojson'
import type { SharedEvent } from '../../types/events'

type GlowStatus = 'affected' | 'risk'
type Target = { id?: string; names: string[]; status: GlowStatus }

type Outline = {
  type: 'Feature'
  geometry: Polygon | MultiPolygon
  properties: { town_id: string; name_he: string | null; name_en: string | null }
}

const SOURCE_ID = 'settlement-glow'
const FILL_ID = 'settlement-glow-fill'
const COLOR: Record<GlowStatus, string> = { affected: '#ef4444', risk: '#facc15' }

/** Which settlements an event touches, and how. */
function targetsOf(event: SharedEvent): Target[] {
  switch (event.type) {
    case 'fire':
      return event.details.exposed_settlements.map((settlement) => ({
        names: [settlement.name_he, settlement.name].filter((name): name is string => Boolean(name)),
        status: settlement.exposure === 'burning' ? 'affected' : 'risk',
      }))
    case 'earthquake':
      return event.details.towns.map((town) => ({ id: town.town_id, names: [], status: 'affected' }))
    case 'air_pollution':
      return event.details.relevant_settlements
        .filter((settlement) => settlement.inside_transport_corridor)
        .map((settlement) => ({ id: settlement.id, names: [settlement.name], status: 'risk' }))
    default:
      return []
  }
}

// One lookup per event per session; failures are dropped so a reopen retries.
const outlineCache = new Map<string, Promise<Outline[]>>()

function fetchOutlines(key: string, targets: Target[]) {
  let request = outlineCache.get(key)
  if (!request) {
    const params = new URLSearchParams()
    for (const target of targets) {
      if (target.id) params.append('id', target.id)
      for (const name of target.names) params.append('name', name)
    }
    request = fetch(`/api/towns/outlines?${params}`).then((response) => {
      if (!response.ok) throw new Error('Town outlines are unavailable')
      return response.json().then((collection: { features: Outline[] }) => collection.features)
    })
    request.catch(() => outlineCache.delete(key))
    outlineCache.set(key, request)
  }
  return request
}

/** The top-centre of a polygon's bounding box: where its name label sits. */
function labelPoint(geometry: Outline['geometry']) {
  const points = geometry.type === 'Polygon' ? geometry.coordinates.flat() : geometry.coordinates.flat(2)
  const longitudes = points.map(([longitude]) => longitude)
  const latitudes = points.map(([, latitude]) => latitude)
  return {
    longitude: (Math.min(...longitudes) + Math.max(...longitudes)) / 2,
    latitude: Math.max(...latitudes),
  }
}

function SettlementGlowLayer({ event }: { event: SharedEvent | null }) {
  const { current: map } = useMap()
  const targets = useMemo(() => (event ? targetsOf(event) : []), [event])
  const eventKey = event ? `${event.type}:${event.id}` : null
  const [outlines, setOutlines] = useState<{ key: string; features: Outline[] } | null>(null)

  useEffect(() => {
    if (!eventKey || targets.length === 0) return
    let active = true
    fetchOutlines(eventKey, targets)
      .then((features) => { if (active) setOutlines({ key: eventKey, features }) })
      .catch(() => { /* no glow is the right failure: the event still shows */ })
    return () => { active = false }
  }, [eventKey, targets])

  // Each outline gets the status of whatever target it matched; "affected"
  // wins if it matched both, since that is the more urgent reading.
  const data = useMemo(() => {
    const features = outlines && outlines.key === eventKey ? outlines.features : []
    return {
      type: 'FeatureCollection' as const,
      features: features.flatMap((feature) => {
        const { town_id: id, name_he: he, name_en: en } = feature.properties
        const matched = targets.filter((target) => (
          target.id === id || target.names.some((name) => name === he || name === en)
        ))
        if (matched.length === 0) return []
        const status: GlowStatus = matched.some((target) => target.status === 'affected') ? 'affected' : 'risk'
        return [{
          ...feature,
          properties: { key: id, name: he ?? en ?? id, status, ...labelPoint(feature.geometry) },
        }]
      }),
    }
  }, [outlines, eventKey, targets])

  // Hover: feature-state for the brighter fill, React state for the label.
  // Both change only when the cursor crosses into a different settlement.
  const [hovered, setHovered] = useState<{ name: string; longitude: number; latitude: number; status: GlowStatus } | null>(null)
  const hoveredId = useRef<string | null>(null)
  // Registered only once the fill layer exists: Mapbox reports a listener on
  // a missing layer as a map error.
  const hasOutlines = data.features.length > 0
  useEffect(() => {
    if (!map || !hasOutlines) return
    const setHover = (id: string, hover: boolean) => {
      if (map.getSource(SOURCE_ID)) map.setFeatureState({ source: SOURCE_ID, id }, { hover })
    }
    const onMove = (mouse: MapLayerMouseEvent) => {
      const feature = mouse.features?.[0]
      const id = feature?.properties?.key as string | undefined
      if (!feature || !id || id === hoveredId.current) return
      if (hoveredId.current) setHover(hoveredId.current, false)
      hoveredId.current = id
      setHover(id, true)
      const { name, longitude, latitude, status } = feature.properties as {
        name: string; longitude: number; latitude: number; status: GlowStatus
      }
      setHovered({ name, longitude, latitude, status })
    }
    const onLeave = () => {
      if (hoveredId.current) setHover(hoveredId.current, false)
      hoveredId.current = null
      setHovered(null)
    }
    map.on('mousemove', FILL_ID, onMove)
    map.on('mouseleave', FILL_ID, onLeave)
    return () => {
      map.off('mousemove', FILL_ID, onMove)
      map.off('mouseleave', FILL_ID, onLeave)
      onLeave()
    }
  }, [map, eventKey, hasOutlines])

  if (!hasOutlines) return null

  const color: ExpressionSpecification = ['match', ['get', 'status'], 'affected', COLOR.affected, COLOR.risk]

  return (
    <>
      <Source id={SOURCE_ID} type="geojson" data={data} promoteId="key">
        <Layer
          id={FILL_ID}
          type="fill"
          slot="middle"
          paint={{
            'fill-color': color,
            'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.24, 0.1],
            'fill-emissive-strength': 1,
          }}
        />
        {/* The glow: a wide blurred edge under a crisp one. */}
        <Layer
          id="settlement-glow-halo"
          type="line"
          slot="middle"
          layout={{ 'line-join': 'round' }}
          paint={{
            'line-color': color,
            'line-width': 8,
            'line-blur': 6,
            'line-opacity': 0.45,
            'line-emissive-strength': 1,
          }}
        />
        <Layer
          id="settlement-glow-edge"
          type="line"
          slot="middle"
          layout={{ 'line-join': 'round' }}
          paint={{
            'line-color': color,
            'line-width': ['case', ['boolean', ['feature-state', 'hover'], false], 2.2, 1.4],
            'line-opacity': 0.95,
            'line-emissive-strength': 1,
          }}
        />
      </Source>

      {hovered && (
        <Marker longitude={hovered.longitude} latitude={hovered.latitude} anchor="bottom" offset={[0, -6]}>
          <span className={`settlement-label settlement-label--${hovered.status}`}>{hovered.name}</span>
        </Marker>
      )}
    </>
  )
}

export default SettlementGlowLayer
