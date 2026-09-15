/**
 * IsraelMask — dims everything outside the operational service area.
 *
 * The map is only meaningful inside the area EcoGuard actually covers, but a
 * basemap happily renders Cairo and Beirut at the same fidelity as Haifa. This
 * draws one polygon over the whole world with the service area punched out of
 * it, so the eye goes where the data is.
 *
 * It is cosmetic, not a security boundary — MapView's maxBounds is what limits
 * panning. The two do different jobs: bounds stop you leaving, this makes the
 * inside obvious.
 */

import { useMemo } from 'react'
import { Layer, Source } from 'react-map-gl/mapbox'

// The same GeoJSON the backend filters cells against, so the mask and the data
// can never disagree about where the service area is.
import serviceAreaText from '../../../../data/reference/ecoguard_service_area.geojson?raw'


type Position = [number, number]
type Ring = Position[]
type PolygonCoordinates = Ring[]

type ServiceGeometry = {
  type: 'Polygon' | 'MultiPolygon'
  coordinates: PolygonCoordinates | PolygonCoordinates[]
}


/**
 * A ring covering the whole planet, wound clockwise.
 *
 * Latitude stops at ±85 rather than ±90 because Web Mercator cannot represent
 * the poles — 90 projects to infinity and the fill fails to render.
 */
const WORLD_RING: Ring = [
  [-180, -85],
  [180, -85],
  [180, 85],
  [-180, 85],
  [-180, -85],
]


/** Matches the dashboard's dark chrome so the mask reads as background. */
const MASK_COLOR = '#0b1220'
const MASK_OPACITY = 0.82


function IsraelMask() {
  const maskGeoJson = useMemo(() => {
    const parsed = JSON.parse(serviceAreaText) as {
      features: Array<{ geometry: ServiceGeometry }>
    }

    const geometry = parsed.features[0].geometry

    const polygons: PolygonCoordinates[] =
      geometry.type === 'Polygon'
        ? [geometry.coordinates as PolygonCoordinates]
        : (geometry.coordinates as PolygonCoordinates[])

    // GeoJSON treats every ring after the first as a hole in the outer one, so
    // the world ring plus each service-area outline gives a world with Israel
    // cut out of it. Inner rings of the source polygon (lakes, enclaves) are
    // ignored on purpose: masking them back in would hide the Sea of Galilee.
    const holes = polygons.map((polygon) => polygon[0])

    return {
      type: 'FeatureCollection' as const,
      features: [
        {
          type: 'Feature' as const,
          properties: {},
          geometry: {
            type: 'Polygon' as const,
            coordinates: [WORLD_RING, ...holes],
          },
        },
      ],
    }
  }, [])

  return (
    <Source
      id="israel-mask"
      type="geojson"
      data={maskGeoJson}
    >
      <Layer
        id="israel-mask-fill"
        type="fill"
        paint={{
          'fill-color': MASK_COLOR,
          'fill-opacity': MASK_OPACITY,
        }}
      />

      <Layer
        id="israel-mask-outline"
        type="line"
        paint={{
          'line-color': '#38bdf8',
          'line-width': 1.2,
          'line-opacity': 0.6,
        }}
      />
    </Source>
  )
}

export default IsraelMask
