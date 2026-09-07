/**
 * FireDangerLayer — the Fire Weather Index, as a heatmap.
 *
 * Renders GWIS/EFFIS FWI over Israel. The data arrives from our own
 * /api/fire-danger as one point per 5 km cell, not from the WMS directly.
 *
 * That indirection is the whole reason this is a smooth field rather than the
 * blocks it used to be. The GWIS raster is coarse and *categorical* — six
 * stepped colours, no gradient — so stretching one PNG across the country
 * upscaled the steps into visible squares and invented nothing in between.
 * The collector samples that raster once per cell, and feathered discs over
 * those samples blend into a surface the point data can actually support.
 *
 * Rendered as blurred circles rather than a heatmap layer on purpose.
 * heatmap-density measures how crowded points are; on a uniform 5 km grid the
 * crowding never varies, so a heatmap flattened every danger band into one
 * colour and discarded the only signal in the data.
 *
 * Coverage stops around latitude 31: Copernicus publishes no FWI over the
 * Negev, because desert has no fuel to index. The gap is the source's and is
 * shown as a gap rather than filled in.
 *
 * It also takes the browser off a third-party WMS: one request to our own API
 * instead of a 900x1200 PNG from Copernicus on every mount.
 *
 * The layer shows environmental fire-weather danger only. It is NOT active
 * fire, and NOT the operational risk score from RiskAnalysisAgent.
 *
 * Data source: GWIS / EFFIS, WMS layer mf010.fwi, via ecoguard's fire_weather
 * collector.
 */

import { useEffect, useState } from 'react'
import { Layer, Source } from 'react-map-gl/mapbox'


type FireDangerLayerProps = {
  /** Whether the FWI overlay is visible. */
  visible?: boolean

  /** Opacity of each cell's disc. Overlapping discs accumulate, so this is
   *  lower than it looks. */
  opacity?: number
}


type FireDangerCollection = {
  type: 'FeatureCollection'
  observed_at: string | null
  features: Array<{
    type: 'Feature'
    geometry: { type: 'Point'; coordinates: [number, number] }
    properties: { cell_id: string; danger_level: string; fwi: number }
  }>
}


const EMPTY: FireDangerCollection = {
  type: 'FeatureCollection',
  observed_at: null,
  features: [],
}


function FireDangerLayer({
  visible = true,
  opacity = 0.45,
}: FireDangerLayerProps) {
  const [data, setData] = useState<FireDangerCollection>(EMPTY)

  useEffect(() => {
    if (!visible) return

    let cancelled = false

    fetch('/api/fire-danger')
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status))
        return response.json()
      })
      .then((collection: FireDangerCollection) => {
        if (!cancelled) setData(collection)
      })
      .catch(() => {
        // A missing FWI layer is a missing layer, not a broken dashboard. The
        // toggle stays available and the next mount retries.
        if (!cancelled) setData(EMPTY)
      })

    return () => {
      cancelled = true
    }
  }, [visible])

  if (!visible || data.features.length === 0) {
    return null
  }

  return (
    <Source
      id="gwis-fwi-source"
      type="geojson"
      data={data}
    >
      <Layer
        id="gwis-fwi-heatmap"
        type="circle"
        paint={{
          // Colour comes from the cell's own FWI band, not from how many
          // points happen to overlap.
          //
          // This started as a heatmap layer and that was the wrong primitive.
          // heatmap-density measures how CROWDED points are, but these sit on
          // a uniform 5 km grid — the density is constant by construction, so
          // the ramp flattened every band into the same green and the real
          // signal was thrown away. A soft circle per cell keeps the value.
          'circle-color': [
            'match',
            ['get', 'danger_level'],
            'low', '#9cffc0',
            'moderate', '#cde24e',
            'high', '#e6ac00',
            'very_high', '#d97010',
            'extreme', '#ad060e',
            'very_extreme', '#580015',
            '#9cffc0',
          ],

          // circle-radius is in screen pixels, so a fixed value breaks into
          // separate dots as the 5 km grid spreads out. An exponential base-2
          // ramp doubles it every zoom level, exactly matching map scale, so
          // each circle covers a constant ~5 km of ground at every zoom and
          // neighbours always overlap by the same amount.
          //
          // ponytail: clamps above z14, where you are well below the 5 km
          // resolution of the data anyway.
          'circle-radius': [
            'interpolate',
            ['exponential', 2],
            ['zoom'],
            6, 3,
            14, 768,
          ],

          // Fully feathered. Hard-edged circles would read as dots; at blur 1
          // the fill fades to nothing at the rim, and overlapping neighbours
          // alpha-blend into a continuous surface.
          'circle-blur': 1,

          'circle-opacity': opacity,

          'circle-stroke-width': 0,
        }}
      />
    </Source>
  )
}

export default FireDangerLayer
