/**
 * FireDangerLayer — the Fire Weather Index, as a smooth interpolated surface.
 *
 * Renders GWIS/EFFIS FWI over Israel from a georeferenced PNG our own backend
 * builds at /api/fire-danger.png, positioned with bounds from
 * /api/fire-danger.
 *
 * Why an image rather than a Mapbox layer over the points: the data is 620
 * samples on a 5 km grid, and Mapbox has no interpolating layer type. A
 * heatmap measures how crowded points are, which on a uniform grid is constant
 * and discards the values entirely. Circles and fills draw one mark per sample,
 * so the grid shows through as dots however they are tuned. Interpolating
 * server-side is the only way to get a continuous surface, and a
 * Gaussian-weighted average with a stated bandwidth is a method rather than a
 * rendering accident.
 *
 * The image is transparent wherever no sample is close enough, so the Negev
 * reads as the absence of data it is: Copernicus publishes no FWI over desert,
 * because desert has no fuel to index.
 *
 * This layer shows environmental fire-weather danger only. It is NOT active
 * fire, and NOT the operational risk score from RiskAnalysisAgent.
 *
 * Data source: GWIS / EFFIS, WMS layer mf010.fwi, sampled per 5 km cell by
 * ecoguard's fire_weather collector.
 */

import { useEffect, useState } from 'react'
import { Layer, Source } from 'react-map-gl/mapbox'


type FireDangerLayerProps = {
  /** Whether the FWI overlay is visible. */
  visible?: boolean

  /** Opacity of the surface above the base map. */
  opacity?: number
}


type FireDangerMeta = {
  observed_at: string | null
  /** west, south, east, north */
  bounds: [number, number, number, number]
  cell_count: number
}


function FireDangerLayer({
  visible = true,
  opacity = 0.6,
}: FireDangerLayerProps) {
  const [meta, setMeta] = useState<FireDangerMeta | null>(null)

  useEffect(() => {
    if (!visible) return

    let cancelled = false

    fetch('/api/fire-danger')
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status))
        return response.json()
      })
      .then((value: FireDangerMeta) => {
        if (!cancelled) setMeta(value)
      })
      .catch(() => {
        // A missing FWI layer is a missing layer, not a broken dashboard.
        if (!cancelled) setMeta(null)
      })

    return () => {
      cancelled = true
    }
  }, [visible])

  if (!visible || !meta || meta.cell_count === 0) {
    return null
  }

  const [west, south, east, north] = meta.bounds

  return (
    <Source
      id="gwis-fwi-source"
      type="image"
      // observed_at busts the browser cache exactly when the data changes and
      // never in between; the endpoint sets a one-hour Cache-Control.
      url={`/api/fire-danger.png?t=${encodeURIComponent(meta.observed_at ?? '')}`}
      coordinates={[
        // Mapbox image coordinates run top-left, top-right, bottom-right,
        // bottom-left.
        [west, north],
        [east, north],
        [east, south],
        [west, south],
      ]}
    >
      <Layer
        id="gwis-fwi-surface"
        type="raster"
        paint={{
          'raster-opacity': opacity,
          // The PNG is already smooth and is being scaled up; nearest-neighbour
          // resampling would reintroduce the very pixel edges it exists to
          // avoid.
          'raster-resampling': 'linear',
          'raster-fade-duration': 300,
        }}
      />
    </Source>
  )
}

export default FireDangerLayer
