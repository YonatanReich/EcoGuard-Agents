/**
 * FireDistrictsLayer — the seven fire & rescue districts, tinted and labelled.
 *
 * Israel's National Fire and Rescue Authority splits the country into seven
 * districts (מחוזות), each subdivided into named areas. This draws the district
 * level only: which authority owns the ground an event lands on.
 *
 * The source shapefile — data/reference/Stations_border.shp — is at area level,
 * 34 polygons. The GeoJSON imported here is those areas dissolved by district,
 * so the internal area borders are gone and only the seven outlines remain. The
 * area names ride along in each feature's `areas` property.
 *
 * Static reference data, bundled at build time like IsraelMask rather than
 * fetched: the districts change about once a decade, and a redraw of the map
 * should never wait on a network round trip for them.
 *
 * Hovering a district fades it up to solid and lights its border, so the
 * operator can pick one out of seven overlapping tints without clicking.
 */

import { useEffect, useMemo, useRef } from 'react'
import { Layer, Source, useMap } from 'react-map-gl/mapbox'
import type { MapLayerMouseEvent } from 'mapbox-gl'

import districtsText from '../../../../data/reference/fire_districts.geojson?raw'


const SOURCE_ID = 'fire-districts'
const FILL_LAYER_ID = 'fire-districts-fill'


/**
 * One colour per district.
 *
 * Qualitative, not sequential — no district outranks another, so the palette
 * only has to keep seven neighbours apart. Tuned for the dark basemap: mid
 * saturation reads through the fill opacity below without competing with the
 * event markers, which own red and orange.
 */
const DISTRICT_COLORS: Record<string, string> = {
  'צפון': '#38bdf8',
  'חוף': '#22d3ee',
  'מרכז': '#a3e635',
  'דן': '#facc15',
  'ירושלים': '#c084fc',
  'יו"ש': '#fb923c',
  'דרום': '#f472b6',
}

const FALLBACK_COLOR = '#94a3b8'

/** Resting fill — low enough that terrain and basemap labels survive under it. */
const FILL_OPACITY = 0.18

/**
 * Hovered fill.
 *
 * Not 1.0 on purpose: fully opaque hides the terrain shading and the towns the
 * operator is hovering to look at in the first place. This reads as solid
 * against its 0.18 neighbours while the ground stays legible. Raise it if you
 * want the district to occlude rather than tint.
 */
const FILL_OPACITY_HOVER = 0.6

/** Glow: a fat blurred line under the crisp outline, faded in only on hover. */
const GLOW_WIDTH = 12
const GLOW_BLUR = 8
const GLOW_OPACITY = 0.55

/**
 * Fade length for every hover transition.
 *
 * Mapbox interpolates paint properties on the GPU, so this costs nothing per
 * frame. Long enough to read as a fade, short enough that sweeping across the
 * country does not leave a trail of still-fading districts behind the cursor.
 */
const HOVER_FADE_MS = 180

/**
 * True while this feature is the hovered one.
 *
 * The second argument is the default for features that have never been given a
 * hover state — without it the expression sees null on first paint and Mapbox
 * falls back to the layer default rather than the resting values below.
 */
const IS_HOVERED = ['boolean', ['feature-state', 'hover'], false]


function FireDistrictsLayer() {
  const { current: map } = useMap()

  /**
   * Which district the cursor is currently over.
   *
   * A ref, not state: mousemove fires at frame rate, and re-rendering on every
   * one is what made this jerk — each render rebuilt the paint expressions and
   * made react-map-gl recompile them across four layers. Hover now never
   * touches React at all; the expressions below are built once and Mapbox
   * animates them from feature-state alone.
   */
  const hoveredRef = useRef<string | number | null>(null)

  const data = useMemo(
    () => JSON.parse(districtsText) as GeoJSON.FeatureCollection,
    [],
  )

  // Mapbox has no "look up a colour in a JS object" expression, so the record
  // above is flattened into a match expression: value, colour, value, colour…
  const colorExpression = useMemo(
    () => [
      'match',
      ['get', 'district'],
      ...Object.entries(DISTRICT_COLORS).flat(),
      FALLBACK_COLOR,
    ],
    [],
  )

  useEffect(() => {
    if (!map) return

    const setHover = (id: string | number, hover: boolean) => {
      map.setFeatureState({ source: SOURCE_ID, id }, { hover })
    }

    const onMove = (event: MapLayerMouseEvent) => {
      const id = event.features?.[0]?.id
      if (id === undefined) return

      // mousemove fires continuously while the cursor sits inside one district.
      // Bailing on an unchanged id keeps the work to the two frames that
      // actually change, which is the other half of the smoothness.
      if (id === hoveredRef.current) return

      if (hoveredRef.current !== null) setHover(hoveredRef.current, false)
      hoveredRef.current = id
      setHover(id, true)
    }

    // Bound to the layer rather than the canvas, so this also fires when the
    // cursor crosses into a gap between districts, not only off the map.
    const clear = () => {
      if (hoveredRef.current === null) return
      setHover(hoveredRef.current, false)
      hoveredRef.current = null
    }

    map.on('mousemove', FILL_LAYER_ID, onMove)
    map.on('mouseleave', FILL_LAYER_ID, clear)

    return () => {
      map.off('mousemove', FILL_LAYER_ID, onMove)
      map.off('mouseleave', FILL_LAYER_ID, clear)

      // Toggling the layer off mid-hover would otherwise leave that district
      // stuck solid when it comes back. Guarded because the source is already
      // gone if the whole map unmounted.
      if (map.getSource(SOURCE_ID)) clear()
    }
  }, [map])

  return (
    <Source
      id={SOURCE_ID}
      type="geojson"
      data={data}
      // feature-state is addressed by feature id, and plain GeoJSON features
      // have none. This promotes the district name into the id slot.
      promoteId="district"
    >
      {/*
        * Drawn before the outline so the blur sits underneath it: the crisp
        * line stays crisp and the glow reads as spill around it.
        */}
      <Layer
        id="fire-districts-glow"
        type="line"
        paint={{
          'line-color': colorExpression as never,
          'line-width': GLOW_WIDTH,
          'line-blur': GLOW_BLUR,
          'line-opacity': ['case', IS_HOVERED, GLOW_OPACITY, 0] as never,
          'line-opacity-transition': { duration: HOVER_FADE_MS },
        }}
      />

      <Layer
        id={FILL_LAYER_ID}
        type="fill"
        paint={{
          'fill-color': colorExpression as never,
          'fill-opacity': [
            'case',
            IS_HOVERED,
            FILL_OPACITY_HOVER,
            FILL_OPACITY,
          ] as never,
          'fill-opacity-transition': { duration: HOVER_FADE_MS },
        }}
      />

      <Layer
        id="fire-districts-outline"
        type="line"
        paint={{
          'line-color': colorExpression as never,
          'line-width': ['case', IS_HOVERED, 3, 1.8] as never,
          'line-width-transition': { duration: HOVER_FADE_MS },
          'line-opacity': 0.9,
        }}
      />

      <Layer
        id="fire-districts-label"
        type="symbol"
        layout={{
          // Mapbox places a point-symbol on a polygon at its pole of
          // inaccessibility, so the name lands inside the district even for
          // the concave ones. No centroid maths needed here.
          'text-field': ['get', 'district'],
          'text-size': 13,
          'text-allow-overlap': false,
        }}
        paint={{
          // Brightening the label is a paint change, so it fades with
          // everything else. Growing it would have been a layout change, which
          // cannot transition and re-flows the whole symbol layer per hover.
          'text-color': ['case', IS_HOVERED, '#ffffff', '#e2e8f0'] as never,
          'text-color-transition': { duration: HOVER_FADE_MS },
          'text-halo-color': '#0b1220',
          'text-halo-width': ['case', IS_HOVERED, 2, 1.4] as never,
          'text-halo-width-transition': { duration: HOVER_FADE_MS },
        }}
      />
    </Source>
  )
}


export default FireDistrictsLayer
