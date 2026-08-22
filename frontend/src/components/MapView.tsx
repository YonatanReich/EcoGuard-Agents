/**
 * MapView — the interactive map of Israel.
 *
 * Responsible for rendering the MapLibre map, its navigation controls, a
 * marker per detected risk event, and a marker for the point the user last
 * clicked. Presentational: it holds no application data and fetches nothing.
 * Clicks are reported upward to Dashboard, which owns the response.
 *
 * Tiles come from MapTiler and require VITE_MAPTILER_KEY. Without it the
 * component renders an explanatory placeholder instead of a broken map.
 *
 * The map is deliberately constrained to Israel: bounded panning, a zoom
 * floor, and rotation disabled to keep the view north-up.
 */

import { useState, type CSSProperties } from 'react'
import Map, {
  NavigationControl,
  ScaleControl,
  FullscreenControl,
  GeolocateControl,
  Marker,
  type MapProps,
} from 'react-map-gl/maplibre'

import maplibregl from 'maplibre-gl'

import 'maplibre-gl/dist/maplibre-gl.css'

import { type RiskEvent } from '../pages/Dashboard'


/**
 * Hebrew and Arabic place names are right-to-left.
 *
 * Vite hot reload can execute this module more than once during development.
 * MapLibre throws an error when setRTLTextPlugin is called repeatedly, so
 * register the plugin only while it is still unavailable.
 */
if (
  maplibregl.getRTLTextPluginStatus() ===
  'unavailable'
) {
  maplibregl.setRTLTextPlugin(
    'https://unpkg.com/@mapbox/mapbox-gl-rtl-text@0.2.3/mapbox-gl-rtl-text.min.js',
    /* lazy */ true,
  )
}


/**
 * MapTiler API key, read from the Vite environment at build time.
 *
 * Set VITE_MAPTILER_KEY in frontend/.env.local.
 */
const MAPTILER_KEY =
  import.meta.env.VITE_MAPTILER_KEY


/**
 * Geographic framing for Israel.
 *
 * MapLibre bounds:
 * [west, south, east, north]
 */
const ISRAEL_CENTER = {
  longitude: 35.0,
  latitude: 31.4,
} as const


const ISRAEL_MAX_BOUNDS: [
  number,
  number,
  number,
  number
] = [
  33.5,
  29.0,
  36.5,
  33.6,
]


type MapViewProps = {
  /**
   * Detected events to plot.
   *
   * Marker colour is derived from risk_level.
   */
  events: RiskEvent[]

  /**
   * Inline style for the wrapping container.
   *
   * Defaults to filling its parent.
   */
  style?: CSSProperties

  /**
   * MapTiler style id.
   *
   * Examples:
   * streets-v2
   * satellite
   * hybrid
   * topo-v2
   */
  mapStyleId?: string

  /**
   * Initial zoom level.
   */
  initialZoom?: number

  /**
   * Extra child layers or markers to render inside the map.
   */
  children?: React.ReactNode

  /**
   * Called with the clicked coordinate for both
   * map clicks and event-marker clicks.
   */
  onClick?: (
    e: any
  ) => void

  /**
   * Coordinate highlighted with the blue marker.
   */
  selectedLocation?: {
    lat: number
    lng: number
  } | null
} & Pick<
  MapProps,
  'onLoad' | 'onClick'
>


/**
 * Render the interactive EcoGuard map.
 *
 * Returns a placeholder instead of the map when
 * the MapTiler API key is missing.
 */
function MapView({
  events,
  style,
  mapStyleId = 'streets-v2',
  initialZoom = 7,
  children,
  onClick,
  selectedLocation,
  ...mapProps
}: MapViewProps) {

  /**
   * Surface a map-tile loading error once instead
   * of leaving the user with a silently broken map.
   */
  const [
    hadError,
    setHadError,
  ] = useState(false)


  const containerStyle: CSSProperties = {
    position: 'relative',
    width: '100%',
    height: '100%',
    ...style,
  }


  if (!MAPTILER_KEY) {
    return (
      <div
        style={{
          ...containerStyle,
          ...messageStyle,
        }}
      >
        <p>
          Map unavailable: set{' '}
          <code>
            VITE_MAPTILER_KEY
          </code>{' '}
          in a{' '}
          <code>
            frontend/.env
          </code>{' '}
          file (see{' '}
          <code>
            .env.example
          </code>
          ).
        </p>
      </div>
    )
  }


  const styleUrl =
    `https://api.maptiler.com/maps/` +
    `${mapStyleId}/style.json` +
    `?key=${MAPTILER_KEY}`


  return (
    <div
      style={containerStyle}
    >

      {hadError && (
        <div
          style={errorBannerStyle}
        >
          Failed to load map tiles — check your
          MapTiler key and network.
        </div>
      )}


      <Map
        initialViewState={{
          ...ISRAEL_CENTER,
          zoom: initialZoom,
        }}

        minZoom={6}

        maxZoom={18}

        maxBounds={
          ISRAEL_MAX_BOUNDS
        }

        mapStyle={
          styleUrl
        }

        /**
         * Keep the map north-up.
         */
        dragRotate={false}

        touchZoomRotate

        attributionControl={{
          compact: true,
        }}

        onError={() =>
          setHadError(true)
        }

        style={{
          width: '100%',
          height: '100%',
        }}

        onClick={
          onClick
        }

        {...mapProps}
      >

        <NavigationControl
          position="top-right"
          visualizePitch={false}
        />


        <GeolocateControl
          position="top-right"
          trackUserLocation
        />


        <FullscreenControl
          position="top-right"
        />


        <ScaleControl
          position="bottom-left"
          unit="metric"
        />


        {selectedLocation && (
          <Marker
            longitude={
              selectedLocation.lng
            }
            latitude={
              selectedLocation.lat
            }
            color="#005eff"
          />
        )}


        {events.map(
          (event) => (
            <Marker
              key={
                event.id
              }

              longitude={
                event.longitude
              }

              latitude={
                event.latitude
              }

              color={
                event.risk_level ===
                'High'
                  ? 'red'
                  : 'orange'
              }

              onClick={(e) => {
                /**
                 * Prevent the marker click from
                 * also triggering the underlying map.
                 */
                e.originalEvent
                  .stopPropagation()

                /**
                 * Forward the marker coordinates
                 * in the same shape as a normal
                 * MapLibre map click.
                 */
                if (onClick) {
                  onClick({
                    lngLat: {
                      lat:
                        event.latitude,

                      lng:
                        event.longitude,
                    },
                  })
                }
              }}
            />
          )
        )}


        {children}

      </Map>

    </div>
  )
}


/**
 * Missing-key placeholder.
 */
const messageStyle: CSSProperties = {
  display: 'flex',

  alignItems: 'center',

  justifyContent: 'center',

  textAlign: 'center',

  padding: '1.5rem',

  background: '#0a1f44',

  color: '#9fb3d1',

  borderRadius: 12,
}


/**
 * Tile-load error banner.
 */
const errorBannerStyle: CSSProperties = {
  position: 'absolute',

  top: 8,

  left: 8,

  zIndex: 2,

  background:
    'rgba(180, 30, 30, 0.92)',

  color: '#fff',

  padding: '6px 10px',

  borderRadius: 6,

  fontSize: '0.85rem',
}


export default MapView