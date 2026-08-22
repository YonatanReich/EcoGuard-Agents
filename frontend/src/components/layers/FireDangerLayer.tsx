/**
 * FireDangerLayer
 *
 * Displays the GWIS/EFFIS Fire Weather Index (FWI) raster over Israel.
 *
 * Unlike RainViewer, GWIS/EFFIS exposes the FWI data through a WMS service
 * rather than standard XYZ tiles. Therefore this component requests one
 * georeferenced PNG covering Israel and uses it as a MapLibre image source.
 *
 * The layer visualizes environmental fire-weather danger only.
 * It does NOT represent active fires and does NOT represent the final
 * operational risk score calculated by RiskAnalysisAgent.
 *
 * Data source:
 *   GWIS / EFFIS
 *
 * WMS layer:
 *   mf010.fwi
 */

import { Layer, Source } from 'react-map-gl/maplibre'


type FireDangerLayerProps = {
  /** Whether the FWI overlay is visible. */
  visible?: boolean

  /** Transparency of the FWI raster above the base map. */
  opacity?: number
}


// Bounding box covering Israel and a small surrounding area.
//
// WMS BBOX order for version 1.1.1 with EPSG:4326:
// west,south,east,north
const FIRE_DANGER_BOUNDS = {
  west: 33.5,
  south: 29.0,
  east: 36.5,
  north: 33.6,
}

const GWIS_WMS_URL =
  'https://maps.effis.emergency.copernicus.eu/effis'


function FireDangerLayer({
  visible = true,
  opacity = 0.55,
}: FireDangerLayerProps) {
  if (!visible) {
    return null
  }

  /**
   * Build the WMS GetMap request dynamically so the date always represents
   * the current day rather than being hard-coded into the frontend.
   */
  const today = new Date().toISOString().split('T')[0]

  const params = new URLSearchParams({
    SERVICE: 'WMS',
    VERSION: '1.1.1',
    REQUEST: 'GetMap',
    LAYERS: 'mf010.fwi',
    STYLES: '',
    SRS: 'EPSG:4326',
    BBOX: [
      FIRE_DANGER_BOUNDS.west,
      FIRE_DANGER_BOUNDS.south,
      FIRE_DANGER_BOUNDS.east,
      FIRE_DANGER_BOUNDS.north,
    ].join(','),
    WIDTH: '900',
    HEIGHT: '1200',
    FORMAT: 'image/png',
    TRANSPARENT: 'true',
    TIME: today,
  })

  const imageUrl = `${GWIS_WMS_URL}?${params.toString()}`

  return (
    <Source
      id="gwis-fwi-source"
      type="image"
      url={imageUrl}
      coordinates={[
        // MapLibre image coordinates must be:
        // top-left, top-right, bottom-right, bottom-left.
        [
          FIRE_DANGER_BOUNDS.west,
          FIRE_DANGER_BOUNDS.north,
        ],
        [
          FIRE_DANGER_BOUNDS.east,
          FIRE_DANGER_BOUNDS.north,
        ],
        [
          FIRE_DANGER_BOUNDS.east,
          FIRE_DANGER_BOUNDS.south,
        ],
        [
          FIRE_DANGER_BOUNDS.west,
          FIRE_DANGER_BOUNDS.south,
        ],
      ]}
    >
      <Layer
        id="gwis-fwi-layer"
        type="raster"
        paint={{
          'raster-opacity': opacity,
          'raster-fade-duration': 0,
        }}
      />
    </Source>
  )
}

export default FireDangerLayer