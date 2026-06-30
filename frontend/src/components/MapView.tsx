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


maplibregl.setRTLTextPlugin(
  'https://unpkg.com/@mapbox/mapbox-gl-rtl-text@0.2.3/mapbox-gl-rtl-text.min.js',
  /* lazy */ true,
)

const MAPTILER_KEY = import.meta.env.VITE_MAPTILER_KEY

// Geographic framing for Israel. maplibre bounds are [west, south, east, north].
// Padded slightly beyond the borders so the country isn't pinned to the viewport edge.
const ISRAEL_CENTER = { longitude: 35.0, latitude: 31.4 } as const
const ISRAEL_MAX_BOUNDS: [number, number, number, number] = [33.5, 29.0, 36.5, 33.6]

type MapViewProps = {
  events: RiskEvent[]
  /** Inline style for the wrapping container. Defaults to filling its parent. */
  style?: CSSProperties
  /** MapTiler style id, e.g. "streets-v2", "satellite", "hybrid", "topo-v2". */
  mapStyleId?: string
  /** Initial zoom level. */
  initialZoom?: number
  /** Extra child layers/markers to render inside the map. */
  children?: React.ReactNode
  onClick?: (e: any) => void
  selectedLocation?: { lat: number; lng: number } | null
} & Pick<MapProps, 'onLoad' | 'onClick'>

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
  // Surface a missing-key error once instead of letting MapTiler return broken tiles.
  const [hadError, setHadError] = useState(false)

  const containerStyle: CSSProperties = {
    position: 'relative',
    width: '100%',
    height: '100%',
    ...style,
  }

  if (!MAPTILER_KEY) {
    return (
      <div style={{ ...containerStyle, ...messageStyle }}>
        <p>
          Map unavailable: set <code>VITE_MAPTILER_KEY</code> in a{' '}
          <code>frontend/.env</code> file (see <code>.env.example</code>).
        </p>
      </div>
    )
  }

  const styleUrl = `https://api.maptiler.com/maps/${mapStyleId}/style.json?key=${MAPTILER_KEY}`

  return (
    <div style={containerStyle}>
      {hadError && (
        <div style={errorBannerStyle}>
          Failed to load map tiles — check your MapTiler key and network.
        </div>
      )}
      <Map
        initialViewState={{
          ...ISRAEL_CENTER,
          zoom: initialZoom,
        }}
        minZoom={6}
        maxZoom={18}
        maxBounds={ISRAEL_MAX_BOUNDS}
        mapStyle={styleUrl}
        // Interaction: drag-pan, scroll/pinch zoom, drag-rotate and touch are
        // all enabled by default in maplibre; keep rotation off for a cleaner
        // north-up dashboard map.
        dragRotate={false}
        touchZoomRotate
        attributionControl={{ compact: true }}
        onError={() => setHadError(true)}
        style={{ width: '100%', height: '100%' }}
        onClick={onClick}
        {...mapProps}
      >
        <NavigationControl position="top-right" visualizePitch={false} />
        <GeolocateControl position="top-right" trackUserLocation />
        <FullscreenControl position="top-right" />
        <ScaleControl position="bottom-left" unit="metric" />

        {selectedLocation && (
          <Marker
            longitude={selectedLocation.lng}
            latitude={selectedLocation.lat}
            color="#005eff" 
          />
        )}

        {events.map((event) => (
          <Marker
            key={event.id}
            longitude={event.longitude}
            latitude={event.latitude}
            color={event.risk_level === 'High' ? 'red' : 'orange'}
            onClick={(e) => {
              e.originalEvent.stopPropagation()
              if (onClick) {
                onClick({
                  lngLat: { lat: event.latitude, lng: event.longitude }
                })
              }
            }}
          />
        ))}

        {children}
      </Map>
    </div>
  )
}

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

const errorBannerStyle: CSSProperties = {
  position: 'absolute',
  top: 8,
  left: 8,
  zIndex: 2,
  background: 'rgba(180, 30, 30, 0.92)',
  color: '#fff',
  padding: '6px 10px',
  borderRadius: 6,
  fontSize: '0.85rem',
}

export default MapView
