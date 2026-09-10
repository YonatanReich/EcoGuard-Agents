/**
 * FireStationsLayer — every fire station in the country, badged on the map.
 *
 * Reads /api/fire-stations, which serves our fire_stations table: the Fire and
 * Rescue Authority's published list, reconciled against the fire stations
 * mapped in OpenStreetMap. Static reference data, so it is fetched once when
 * the layer is first switched on and then held — unlike radar or FWI there is
 * nothing to refresh.
 *
 * Drawn as a Mapbox symbol layer carrying the Fire and Rescue Authority badge,
 * rather than React markers: a hundred markers are a hundred DOM nodes
 * repositioning on every pan frame, while a symbol layer is one GPU draw call
 * that scales with zoom through a layout expression.
 *
 * Not every station is equally well placed, and the layer says so rather than
 * drawing them all as though they were surveyed: a station matched to its
 * mapped building is exact, one derived from a postal address is not, and the
 * ten with no coordinates at all cannot be drawn. `located` and `total` are
 * exposed so the UI can admit the gap.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Layer, Popup, Source, useMap } from 'react-map-gl/mapbox'

import { BADGE_SIZE_BY_ZOOM, useStationBadge } from './stationBadges'
import { useStationReveal, withLatitude } from './useStationReveal'

import '../../pages/visuals/firestationpopup.css'


/**
 * Exported so the dashboard can name it in the map's interactiveLayerIds
 * without repeating the string, and so its click handler can tell a click on a
 * station from a click on open ground.
 */
export const FIRE_STATIONS_LAYER_ID = 'fire-stations-dots'

/** Must outlast the close transition in firestationpopup.css. */
const CLOSE_MS = 150


/**
 * What each dot's position is derived from. Only "building" is the station
 * itself, matched to the mapped fire station in OpenStreetMap. The rest are the
 * published postal address resolved to progressively coarser things, and "city"
 * is the town centroid — which in a large city is kilometres from the station.
 */
const POSITION_BASIS: Record<string, { label: string; tone: string }> = {
  building: { label: 'מיקום מדויק — מבנה התחנה', tone: 'exact' },
  street: { label: 'מיקום מקורב — רחוב התחנה', tone: 'near' },
  neighborhood: { label: 'מיקום מקורב — שכונה', tone: 'near' },
  city: { label: 'מיקום משוער — מרכז היישוב', tone: 'rough' },
}


type FireStationsLayerProps = {
  /** Whether the fire station dots are visible. */
  visible?: boolean

  /**
   * Called once with how many of the listed stations carry coordinates, so the
   * control above the map can say "108 of 118 mapped" rather than letting the
   * map imply the list is complete.
   */
  onLoaded?: (counts: { located: number; total: number }) => void
}


type SelectedStation = {
  longitude: number
  latitude: number
  name: string
  district: string
  regional: boolean
  address: string | null
  precision: string | null
  phone?: string
  website?: string
  opening_hours?: string
  operator?: string
}


export type FireStationsCollection = GeoJSON.FeatureCollection & {
  /** Stations with coordinates — the ones actually drawn. */
  located: number
  /** Stations in the table, drawn or not. */
  total: number
}


function FireStationsLayer({
  visible = true,
  onLoaded,
}: FireStationsLayerProps) {
  const [stations, setStations] = useState<FireStationsCollection | null>(null)
  const [selected, setSelected] = useState<SelectedStation | null>(null)
  const [closing, setClosing] = useState(false)
  const closeTimer = useRef<number | null>(null)
  const { current: map } = useMap()
  const badgeReady = useStationBadge(map, 'fire-station-badge', '/FireDepIsrael.svg', '#dc2626')
  const reveal = useStationReveal(visible, ['case', ['==', ['get', 'precision'], 'city'], 0.45, 1])

  // The reveal re-renders this component on every animation frame, and
  // withLatitude builds a new collection each time it runs. Without this the
  // GeoJSON source would be replaced sixty times a second.
  const data = useMemo(
    () => (stations ? withLatitude(stations) : null),
    [stations],
  )

  // Unmounting on the same frame as the close would leave nothing to animate,
  // so the popup is held for the length of the transition first.
  const dismiss = useCallback(() => {
    if (closeTimer.current !== null) return
    setClosing(true)
    closeTimer.current = window.setTimeout(() => {
      setSelected(null)
      setClosing(false)
      closeTimer.current = null
    }, CLOSE_MS)
  }, [])

  const cancelDismiss = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
    setClosing(false)
  }, [])

  useEffect(() => () => {
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current)
  }, [])

  useEffect(() => {
    // Nothing to re-fetch on a toggle: the list does not change while the
    // dashboard is open, so once it is loaded the effect is a no-op.
    if (!visible || stations) return

    let cancelled = false

    fetch('/api/fire-stations')
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status))
        return response.json()
      })
      .then((value: FireStationsCollection) => {
        if (cancelled) return
        setStations(value)
        onLoaded?.({ located: value.located, total: value.total })
      })
      .catch(() => {
        // A missing station layer is a missing layer, not a broken dashboard.
        if (!cancelled) setStations(null)
      })

    return () => {
      cancelled = true
    }
  }, [visible, stations])

  // A layer-scoped listener rather than the map's own onClick: Mapbox only
  // fires this for clicks that actually hit a dot, so the dashboard's
  // click-anywhere handler stays the dashboard's business.
  useEffect(() => {
    if (!map || !visible) return

    const openPopup = (event: any) => {
      const feature = event.features?.[0]
      if (!feature) return

      const [longitude, latitude] = feature.geometry.coordinates
      // Clicking a second dot while one is fading out must cancel that fade,
      // or the new card inherits the old one's closing state and never appears.
      cancelDismiss()
      setSelected({ longitude, latitude, ...feature.properties })
    }

    const enter = () => { map.getCanvas().style.cursor = 'pointer' }
    const leave = () => { map.getCanvas().style.cursor = '' }

    map.on('click', FIRE_STATIONS_LAYER_ID, openPopup)
    map.on('mouseenter', FIRE_STATIONS_LAYER_ID, enter)
    map.on('mouseleave', FIRE_STATIONS_LAYER_ID, leave)

    return () => {
      map.off('click', FIRE_STATIONS_LAYER_ID, openPopup)
      map.off('mouseenter', FIRE_STATIONS_LAYER_ID, enter)
      map.off('mouseleave', FIRE_STATIONS_LAYER_ID, leave)
      leave()
    }
  }, [map, visible, cancelDismiss])

  // Switching the layer off must take its popup with it, or the card is left
  // pointing at a dot that is no longer drawn.
  useEffect(() => {
    if (!visible) {
      setSelected(null)
      setClosing(false)
    }
  }, [visible])

  if (!reveal.mounted || !data || !badgeReady) {
    return null
  }

  const basis = POSITION_BASIS[selected?.precision ?? ''] ?? {
    label: 'מיקום משוער',
    tone: 'rough',
  }

  return (
    <>
      <Source id="fire-stations-source" type="geojson" data={data}>
        <Layer
          id={FIRE_STATIONS_LAYER_ID}
          type="symbol"
          layout={{
            'icon-image': 'fire-station-badge',
            'icon-size': BADGE_SIZE_BY_ZOOM,
            // Without this Mapbox hides colliding icons, and the coastal
            // strip would silently drop most of its stations.
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
          }}
          paint={{ 'icon-opacity': reveal.opacity }}
        />
      </Source>

      {selected && (
        <Popup
          longitude={selected.longitude}
          latitude={selected.latitude}
          anchor="bottom"
          offset={16}
          closeOnClick={false}
          maxWidth="290px"
          className={`station-popup ${closing ? 'station-popup--closing' : 'station-popup--open'}`}
          onClose={dismiss}
        >
          <div className="station-card">
            <div className="station-card__name">{selected.name}</div>

            <div className="station-card__meta">
              מחוז {selected.district}
              {selected.regional && ' · תחנה אזורית'}
              {selected.opening_hours && ` · ${selected.opening_hours}`}
            </div>

            {selected.address && (
              <div className="station-card__address">{selected.address}</div>
            )}

            {(selected.phone || selected.website) && (
              <div className="station-card__contact">
                {selected.phone && (
                  <a href={`tel:${selected.phone.replace(/\s/g, '')}`}>
                    {selected.phone}
                  </a>
                )}
                {selected.website && (
                  <a href={selected.website} target="_blank" rel="noreferrer">
                    אתר הרשות
                  </a>
                )}
              </div>
            )}

            {/* Every card states what its dot actually is. Three of the four
                bases are approximations, and a card that stays quiet about it
                is a dot claiming to be surveyed. */}
            <div className="station-card__basis">
              <span className={`station-card__dot station-card__dot--${basis.tone}`} />
              {basis.label}
            </div>
          </div>
        </Popup>
      )}
    </>
  )
}

export default FireStationsLayer
