/**
 * AreaSelect — draw an area on the map and read what is inside it.
 *
 * This replaced clicking a coordinate. A point could only ever answer "what is
 * the temperature here"; the question an operator actually has is "how many
 * people are inside this, and what is the weather doing across it", and only
 * an enclosed area answers that.
 *
 * Three ways to enclose one, because they suit different questions:
 *   - freehand, for the irregular shape of a valley or a fire's likely path
 *   - rectangle, for a quick bounding read of a district
 *   - circle, for "within N km of this point"
 *
 * All three produce the same thing — a GeoJSON Polygon — which is posted to
 * /api/area-summary and aggregated in PostGIS. Nothing is computed here.
 *
 * Drawing is implemented against the map's own mouse events rather than by
 * adding a drawing library. mapbox-gl-draw covers the rectangle and neither of
 * the other two without further plugins, and the whole of what we need is
 * "collect points between mousedown and mouseup" — three ring builders below,
 * and no dependency to keep in step with the Mapbox version.
 */

import { useEffect, useRef, useState } from 'react'
import { Layer, Source, useMap } from 'react-map-gl/mapbox'

import '../pages/visuals/areaselect.css'


/** What the user is drawing, or 'off' when the map pans normally. */
type DrawMode = 'off' | 'freehand' | 'rectangle' | 'circle'

/** A closed GeoJSON linear ring: [longitude, latitude] pairs, first repeated last. */
type Ring = [number, number][]

/** One drag in progress: where it started, and what the hand has traced so far. */
type Gesture = {
  origin: { lng: number; lat: number }
  originPixel: { x: number; y: number }
  lastPixel: { x: number; y: number }
  trace: [number, number][]
}

type AreaSummary = {
  area_km2: number
  population: number
  weather: {
    temperature_c: number | null
    humidity_percent: number | null
    wind_speed_kmh: number | null
    wind_gust_max_kmh: number | null
    wind_direction_deg: number | null
    precipitation_mm: number | null
    observed_at: string | null
    cell_count: number
  }
  fire_danger: {
    fwi: number | null
    worst_level: string | null
    cell_count: number
    observed_at: string | null
  }
  stations: { fire: number; police: number; mda: number }
}


/**
 * Israel's bounding box, matching what the endpoint accepts.
 *
 * The map deliberately lets the camera wander past the border, so a drawn
 * shape can too. Vertices are clamped into the box rather than the whole
 * drawing being rejected: everything behind the numbers — the population grid,
 * the weather cells, the stations — stops at the border anyway, so the clipped
 * shape is the honest one.
 */
const BOUNDS = { west: 34.26, south: 29.45, east: 35.90, north: 33.35 }

/** Segments in a drawn circle. 64 is smooth past any zoom the map allows. */
const CIRCLE_SEGMENTS = 64

/**
 * Rough metres per degree of latitude. Only used to turn a drag into a circle
 * radius, where being half a percent out is invisible; every distance and area
 * that is reported comes from PostGIS on the spheroid.
 */
const METRES_PER_DEGREE = 111_320

/** Minimum drag, in pixels, before a gesture counts as a shape rather than a click. */
const MINIMUM_DRAG_PX = 8

/**
 * Freehand vertices are dropped unless this far from the previous one, and the
 * trace stops growing at the cap. Together they keep a slow, wandering drag
 * under the endpoint's vertex limit — and past a few hundred points the extra
 * detail is finer than the 100 m population grid can answer to anyway.
 */
const FREEHAND_MIN_STEP_PX = 5
const FREEHAND_MAX_POINTS = 1_200


const clamp = (value: number, low: number, high: number) =>
  Math.min(Math.max(value, low), high)

const inBounds = (longitude: number, latitude: number): [number, number] => [
  clamp(longitude, BOUNDS.west, BOUNDS.east),
  clamp(latitude, BOUNDS.south, BOUNDS.north),
]

/** Close a ring by repeating its first position, as GeoJSON requires. */
const closed = (points: [number, number][]): Ring =>
  points.length ? [...points, points[0]] : []

const rectangleRing = (
  a: { lng: number; lat: number },
  b: { lng: number; lat: number },
): Ring =>
  closed([
    inBounds(a.lng, a.lat),
    inBounds(b.lng, a.lat),
    inBounds(b.lng, b.lat),
    inBounds(a.lng, b.lat),
  ])

/**
 * A circle around `centre` passing through `edge`.
 *
 * Longitude degrees are scaled by cos(latitude) so the result is round on the
 * ground rather than an ellipse stretched east-west — over Israel that is a
 * 15% difference, which is very visible.
 */
const circleRing = (
  centre: { lng: number; lat: number },
  edge: { lng: number; lat: number },
): Ring => {
  const shrink = Math.cos((centre.lat * Math.PI) / 180)
  const northing = (edge.lat - centre.lat) * METRES_PER_DEGREE
  const easting = (edge.lng - centre.lng) * METRES_PER_DEGREE * shrink
  const radius = Math.hypot(northing, easting)

  const points: [number, number][] = []
  for (let step = 0; step < CIRCLE_SEGMENTS; step += 1) {
    const angle = (step / CIRCLE_SEGMENTS) * 2 * Math.PI
    points.push(inBounds(
      centre.lng + (radius * Math.sin(angle)) / (METRES_PER_DEGREE * shrink),
      centre.lat + (radius * Math.cos(angle)) / METRES_PER_DEGREE,
    ))
  }
  return closed(points)
}


const MODES: { mode: Exclude<DrawMode, 'off'>; icon: string; label: string }[] = [
  { mode: 'freehand', icon: '✎', label: 'Freehand' },
  { mode: 'rectangle', icon: '▭', label: 'Rectangle' },
  { mode: 'circle', icon: '◯', label: 'Circle' },
]

const HINTS: Record<Exclude<DrawMode, 'off'>, string> = {
  freehand: 'Drag to trace an area.',
  rectangle: 'Drag from one corner to the opposite one.',
  circle: 'Drag from the centre outward.',
}


export default function AreaSelect() {
  const { current: map } = useMap()

  const [mode, setMode] = useState<DrawMode>('off')
  /** The finished shape, or the one currently under the cursor. */
  const [ring, setRing] = useState<Ring | null>(null)
  const [summary, setSummary] = useState<AreaSummary | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /**
   * The in-progress gesture. A ref rather than state: these change on every
   * mousemove, and re-rendering the whole dashboard sixty times a second to
   * store a cursor position would make the drag stutter. Only the resulting
   * ring goes into state, which is what the map has to redraw anyway.
   */
  const drag = useRef<Gesture | null>(null)

  const request = useRef(0)

  const load = (geometry: { type: 'Polygon'; coordinates: Ring[] }) => {
    // Each drawing invalidates the one before it. Without this counter a slow
    // response to an earlier shape can land after a faster response to a later
    // one and leave the panel describing an area that is no longer on screen.
    const ticket = request.current + 1
    request.current = ticket

    setIsLoading(true)
    setError(null)
    setSummary(null)

    fetch('/api/area-summary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ geometry }),
    })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(
            typeof body?.detail === 'string' ? body.detail : `Error ${response.status}`,
          )
        }
        return response.json() as Promise<AreaSummary>
      })
      .then((data) => {
        if (request.current === ticket) setSummary(data)
      })
      .catch((failure: Error) => {
        if (request.current === ticket) setError(failure.message || 'Could not read this area')
      })
      .finally(() => {
        if (request.current === ticket) setIsLoading(false)
      })
  }

  useEffect(() => {
    if (!map || mode === 'off') return

    const target = map.getMap()

    // Panning and drawing are the same gesture, so one has to give way. The
    // mode buttons are what turns dragging back into panning.
    target.dragPan.disable()
    target.getCanvas().style.cursor = 'crosshair'

    // Takes the gesture rather than reading the ref, so it cannot be called
    // after mouseup has already cleared it — which is a silent null, not an
    // error, and loses the finished shape.
    const ringFor = (gesture: Gesture, position: { lng: number; lat: number }): Ring => {
      if (mode === 'rectangle') return rectangleRing(gesture.origin, position)
      if (mode === 'circle') return circleRing(gesture.origin, position)
      return closed(gesture.trace)
    }

    const onDown = (event: mapboxgl.MapMouseEvent) => {
      const { lng, lat } = event.lngLat
      drag.current = {
        origin: { lng, lat },
        originPixel: { ...event.point },
        lastPixel: { ...event.point },
        trace: [inBounds(lng, lat)],
      }
      setSummary(null)
      setError(null)
    }

    const onMove = (event: mapboxgl.MapMouseEvent) => {
      const gesture = drag.current
      if (!gesture) return

      if (mode === 'freehand') {
        const step = Math.hypot(
          event.point.x - gesture.lastPixel.x,
          event.point.y - gesture.lastPixel.y,
        )
        if (step < FREEHAND_MIN_STEP_PX) return
        gesture.lastPixel = { ...event.point }
        if (gesture.trace.length < FREEHAND_MAX_POINTS) {
          gesture.trace.push(inBounds(event.lngLat.lng, event.lngLat.lat))
        }
      }

      setRing(ringFor(gesture, event.lngLat))
    }

    const onUp = (event: mapboxgl.MapMouseEvent) => {
      const gesture = drag.current
      if (!gesture) return
      drag.current = null

      const travelled = Math.hypot(
        event.point.x - gesture.originPixel.x,
        event.point.y - gesture.originPixel.y,
      )
      const finished = ringFor(gesture, event.lngLat)

      // A click, or a shape too small to have an inside. Clear it rather than
      // asking the server about a degenerate polygon.
      if (travelled < MINIMUM_DRAG_PX || finished.length < 4) {
        setRing(null)
        return
      }

      setRing(finished)
      setMode('off')
      load({ type: 'Polygon', coordinates: [finished] })
    }

    target.on('mousedown', onDown)
    target.on('mousemove', onMove)
    target.on('mouseup', onUp)

    return () => {
      target.off('mousedown', onDown)
      target.off('mousemove', onMove)
      target.off('mouseup', onUp)
      target.dragPan.enable()
      target.getCanvas().style.cursor = ''
      drag.current = null
    }
    // ponytail: mouse only. Add the touch equivalents when someone actually
    // draws on a tablet — the handlers above are the same three events.
  }, [map, mode])

  const clear = () => {
    setMode('off')
    setRing(null)
    setSummary(null)
    setError(null)
    request.current += 1
  }

  return (
    <>
      {ring && (
        <Source
          id="area-select"
          type="geojson"
          data={{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } }}
        >
          <Layer
            id="area-select-fill"
            type="fill"
            paint={{ 'fill-color': '#38bdf8', 'fill-opacity': 0.18 }}
          />
          <Layer
            id="area-select-outline"
            type="line"
            paint={{ 'line-color': '#38bdf8', 'line-width': 2 }}
          />
        </Source>
      )}

      <div className="area-select">

        {summary && !isLoading && <SummaryPanel summary={summary} />}

        {isLoading && (
          <div className="area-select__panel">
            <p className="area-select__error" style={{ color: '#374151' }}>Reading the area…</p>
          </div>
        )}

        {error && !isLoading && (
          <div className="area-select__panel">
            <p className="area-select__error">{error}</p>
          </div>
        )}

        {mode !== 'off' && <div className="area-select__hint">{HINTS[mode]}</div>}

        <div className="area-select__modes">
          {MODES.map(({ mode: option, icon, label }) => (
            <button
              key={option}
              type="button"
              className="area-select__mode"
              aria-pressed={mode === option}
              title={`Draw an area — ${label.toLowerCase()}`}
              onClick={() => setMode((current) => (current === option ? 'off' : option))}
            >
              <span aria-hidden="true">{icon}</span>
              {label}
            </button>
          ))}

          {(ring || summary || error) && (
            <button
              type="button"
              className="area-select__mode area-select__mode--clear"
              title="Remove the drawn area"
              onClick={clear}
            >
              ✕
            </button>
          )}
        </div>

      </div>
    </>
  )
}


/** One reading, or an em dash where there is nothing to report. */
function Row({ label, value }: { label: string; value: string | null }) {
  return (
    <>
      <span className="area-select__label">{label}</span>
      <span className="area-select__value">{value ?? '—'}</span>
    </>
  )
}

const number = (value: number | null, unit: string) =>
  value === null ? null : `${value.toLocaleString()} ${unit}`


function SummaryPanel({ summary }: { summary: AreaSummary }) {
  const { weather, fire_danger: fire, stations } = summary
  const stationTotal = stations.fire + stations.police + stations.mda

  return (
    <div className="area-select__panel">
      <h3 className="area-select__title">Selected area</h3>

      <div className="area-select__rows">
        <Row label="Area" value={number(summary.area_km2, 'km²')} />
        <Row label="Population" value={summary.population.toLocaleString()} />
        <Row label="Temperature" value={number(weather.temperature_c, '°C')} />
        <Row label="Humidity" value={number(weather.humidity_percent, '%')} />
        <Row label="Wind" value={number(weather.wind_speed_kmh, 'km/h')} />
        <Row label="Gusts" value={number(weather.wind_gust_max_kmh, 'km/h')} />
        <Row label="Precipitation" value={number(weather.precipitation_mm, 'mm')} />
        <Row
          label="Fire danger"
          value={fire.fwi === null ? null : `${fire.fwi} FWI · ${fire.worst_level?.replace('_', ' ')} peak`}
        />
        <Row
          label="Stations"
          value={
            stationTotal === 0
              ? 'none inside'
              : `${stations.fire} fire · ${stations.police} police · ${stations.mda} MDA`
          }
        />
      </div>

      <p className="area-select__note">
        {weather.cell_count === 0
          ? 'No weather cell covers this area.'
          : `Averaged over ${weather.cell_count} weather cell${weather.cell_count === 1 ? '' : 's'}` +
            (weather.observed_at
              ? `, read ${new Date(weather.observed_at).toLocaleString('en-GB', {
                  hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short',
                })}.`
              : '.')}
      </p>
    </div>
  )
}
