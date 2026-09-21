/**
 * MapView — the interactive map of Israel.
 *
 * Responsible for rendering the MapLibre map, its navigation controls and a
 * marker per detected risk event. Presentational: it holds no application data
 * and fetches nothing.
 *
 * The map itself has no click behaviour. Layers that need one — the station
 * dots, the area drawing tool — attach their own listeners through useMap, so
 * a click belongs to whatever drew the thing under it rather than being routed
 * up to Dashboard and dispatched back down.
 *
 * Tiles come from Mapbox and require VITE_MAPBOX_KEY. Without it the
 * component renders an explanatory placeholder instead of a broken map.
 *
 * The map is deliberately constrained to Israel: bounded panning, a zoom
 * floor, and an IsraelMask that greys out everything past the service area.
 * Unlike the previous MapTiler setup the camera can tilt and rotate, because
 * the terrain is the point — slope and aspect drive fire behaviour.
 */

import { useState, type CSSProperties } from 'react'
import Map, {
  NavigationControl,
  ScaleControl,
  FullscreenControl,
  GeolocateControl,
  Marker,
  type MapProps,
  Source,
} from 'react-map-gl/mapbox'

import mapboxgl from 'mapbox-gl'

import 'mapbox-gl/dist/mapbox-gl.css'

import IsraelMask from './layers/IsraelMask'
import FloodEventLayer from './layers/FloodEventLayer'
import { classify, hazardOf } from './hazards'

import type { SharedEvent } from '../types/events'


/**
 * Hebrew and Arabic place names are right-to-left.
 *
 * Vite hot reload can execute this module more than once during development.
 * Mapbox throws an error when setRTLTextPlugin is called repeatedly, so
 * register the plugin only while it is still unavailable.
 */
if (
  mapboxgl.getRTLTextPluginStatus() ===
  'unavailable'
) {
  mapboxgl.setRTLTextPlugin(
    'https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-rtl-text/v0.2.3/mapbox-gl-rtl-text.js',
    /* callback */ undefined,
    /* lazy */ true,
  )
}


/**
 * Mapbox public access token, read from the Vite environment at build time.
 *
 * Set VITE_MAPBOX_KEY in frontend/.env. A pk.* token is meant to be visible in
 * the bundle; restrict it by URL in the Mapbox dashboard rather than trying to
 * hide it.
 */
const MAPBOX_KEY =
  import.meta.env.VITE_MAPBOX_KEY


/**
 * Mapbox Standard: 3D buildings, landmarks and time-of-day lighting built in.
 */
const MAP_STYLE = 'mapbox://styles/mapbox/standard'


/**
 * Mapbox's global terrain DEM, and how hard to push it.
 *
 * Israel's relief is modest — the Carmel and the Galilee are only a few
 * hundred metres — so at exaggeration 1.0 the terrain is invisible at national
 * zoom. 1.4 makes slope readable without turning the Negev into the Alps.
 */
const TERRAIN_SOURCE = 'mapbox-dem'
const TERRAIN_EXAGGERATION = 1.4


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


/**
 * Deliberately wider than the country.
 *
 * A tilted camera sees far more ground than a top-down one, and MapLibre-style
 * bounds clamp the *visible* area — so bounds drawn tight to the coastline
 * make the map fight every attempt to pitch. The mask, not these bounds, is
 * what keeps the user looking at Israel; these only stop them wandering to
 * Europe.
 */
const ISRAEL_MAX_BOUNDS: [
  number,
  number,
  number,
  number
] = [
  32.0,
  28.0,
  38.0,
  34.6,
]


/** Tilt hard enough that relief reads, not so hard the horizon dominates. */
const INITIAL_PITCH = 45
const MAX_PITCH = 75


type MapViewProps = {
  /**
   * Detected events to plot.
   *
   * Marker colour is derived from the canonical hazard type.
   */
  events: SharedEvent[]

  /**
   * Inline style for the wrapping container.
   *
   * Defaults to filling its parent.
   */
  style?: CSSProperties

  /**
   * Override the basemap style.
   *
   * Examples:
   * mapbox://styles/mapbox/standard
   * mapbox://styles/mapbox/standard-satellite
   * mapbox://styles/mapbox/satellite-streets-v12
   *
   * Defaults to Standard, which is the one with 3D buildings and lighting.
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
   * Called when an event marker is clicked, so the card list and the map
   * open the same modal.
   */
  onEventClick?: (event: SharedEvent) => void

  /** Whether the Flood event overlay is visible. */
  showFloodEvents?: boolean
} & Pick<MapProps, 'onLoad'>


/**
 * Render the interactive EcoGuard map.
 *
 * Returns a placeholder instead of the map when
 * the MapTiler API key is missing.
 */
function MapView({
  events,
  style,
  mapStyleId,
  initialZoom = 7,
  children,
  onEventClick,
  showFloodEvents = true,
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


  if (!MAPBOX_KEY) {
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
            VITE_MAPBOX_KEY
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


  return (
    <div
      style={containerStyle}
    >

      {hadError && (
        <div
          style={errorBannerStyle}
        >
          Failed to load map tiles — check your
          Mapbox token and network.
        </div>
      )}


      <Map
        mapboxAccessToken={
          MAPBOX_KEY
        }

        initialViewState={{
          ...ISRAEL_CENTER,
          zoom: initialZoom,
          pitch: INITIAL_PITCH,
          bearing: 0,
        }}

        minZoom={6}

        maxZoom={18}

        maxPitch={MAX_PITCH}

        maxBounds={
          ISRAEL_MAX_BOUNDS
        }

        mapStyle={
          mapStyleId ?? MAP_STYLE
        }

        /**
         * Drape the basemap over real elevation. Without this the pitch above
         * only tilts a flat plane, which looks 3D but tells you nothing.
         */
        terrain={{
          source: TERRAIN_SOURCE,
          exaggeration:
            TERRAIN_EXAGGERATION,
        }}

        touchZoomRotate

        /**
         * Mapbox takes a boolean here where MapLibre took an options object.
         * It compacts itself on narrow viewports, and Mapbox's terms require
         * the attribution stay visible, so this is on deliberately.
         */
        attributionControl

        onError={() =>
          setHadError(true)
        }

        style={{
          width: '100%',
          height: '100%',
        }}

        {...mapProps}
      >

        <Source
          id={TERRAIN_SOURCE}
          type="raster-dem"
          url="mapbox://mapbox.mapbox-terrain-dem-v1"
          tileSize={512}
          maxzoom={14}
        />


        <IsraelMask />


        <NavigationControl
          position="top-right"
          visualizePitch
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


        {events.filter((event) => event.type !== 'flood').map(
          (event) => {
            const hazard = hazardOf(event)
            const isEmergency =
              classify(event) === 'emergency'

            return (
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

                onClick={(e) => {
                  /**
                   * Prevent the marker click from
                   * also triggering the underlying map.
                   */
                  e.originalEvent
                    .stopPropagation()

                  if (onEventClick) {
                    onEventClick(event)
                  }
                }}
              >
                {/*
                  * Hazard sets the colour, urgency sets the pulse. Two
                  * independent signals on one mark, so an operator can read
                  * "which kind" and "how urgent" without a lookup.
                  */}
                <span
                  className={
                    'map-marker' +
                    (isEmergency
                      ? ' map-marker--emergency'
                      : '')
                  }
                  style={{
                    '--hazard': hazard.color,
                    '--hazard-halo': hazard.halo,
                  } as CSSProperties}
                  title={event.title}
                />
              </Marker>
            )
          }
        )}

        {showFloodEvents && events.filter((event) => event.type === 'flood').map((event) => (
          <FloodEventLayer
            key={event.id}
            event={event}
            onEventClick={onEventClick}
          />
        ))}


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
