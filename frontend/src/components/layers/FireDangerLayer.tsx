/**
 * FireDangerLayer — the Fire Weather Index, as a heatmap.
 *
 * Renders GWIS/EFFIS FWI over Israel. The data arrives from our own
 * /api/fire-danger as one point per 5 km cell, not from the WMS directly.
 *
 * That indirection is the whole reason this looks like a heatmap rather than
 * the blocks it used to. The GWIS raster is coarse and *categorical* — six
 * stepped colours, no gradient — so stretching one PNG across the country
 * upscaled the steps into visible squares and invented nothing in between.
 * The collector samples that raster once per cell; interpolating between those
 * samples is a claim the point data can actually support.
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

  /** Peak opacity of the heatmap above the base map. */
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


/**
 * The FWI band boundaries, as heatmap weights.
 *
 * Weight is normalised 0..1 across the range the legend spans, so a cell in
 * the "extreme" band pushes the heatmap roughly twice as hard as one in
 * "high". Anchoring on the legend keeps the colours meaning the same thing
 * they do in the sidebar.
 */
const FWI_MIN = 0
const FWI_MAX = 80


function FireDangerLayer({
  visible = true,
  opacity = 0.75,
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
        type="heatmap"
        paint={{
          // Each cell contributes in proportion to its danger band.
          'heatmap-weight': [
            'interpolate',
            ['linear'],
            ['get', 'fwi'],
            FWI_MIN, 0,
            FWI_MAX, 1,
          ],

          // Cells sit on a fixed 5 km grid, so as you zoom in they spread
          // apart and the blend thins. Raising intensity with zoom keeps the
          // surface reading at the same strength all the way in.
          'heatmap-intensity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            6, 1,
            12, 3,
          ],

          // The GWIS legend's own ramp, so the map and the sidebar agree.
          // Density 0 must be fully transparent or the heatmap paints a wash
          // over the entire country instead of only where cells are.
          'heatmap-color': [
            'interpolate',
            ['linear'],
            ['heatmap-density'],
            0.0, 'rgba(0, 0, 0, 0)',
            0.15, 'rgba(156, 255, 192, 0.5)',
            0.3, 'rgba(205, 226, 78, 0.65)',
            0.5, 'rgba(230, 172, 0, 0.75)',
            0.7, 'rgba(217, 112, 16, 0.85)',
            0.85, 'rgba(173, 6, 14, 0.9)',
            1.0, 'rgba(88, 0, 21, 0.95)',
          ],

          // Roughly half a cell at national zoom, growing so neighbouring
          // cells keep overlapping as they separate on screen. Too small and
          // the grid reappears as dots; too large and everything smears.
          'heatmap-radius': [
            'interpolate',
            ['linear'],
            ['zoom'],
            6, 18,
            9, 40,
            12, 90,
          ],

          'heatmap-opacity': opacity,
        }}
      />
    </Source>
  )
}

export default FireDangerLayer
