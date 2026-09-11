/**
 * PoliceStationsLayer — every police station in the country, badged on the map.
 *
 * Reads /api/police-stations, which serves the Israel Police published list out
 * of our own police_stations table. Static reference data, fetched once when
 * the layer is first switched on.
 *
 * Marked with the Israel Police emblem on a white disc inside a blue ring, the
 * same badge shape the other two services use, so the three read as one set
 * and are told apart by their emblem rather than by colour alone.
 *
 * A deliberate sibling of FireStationsLayer rather than a shared generic one:
 * the two differ in endpoint, colour, popup body and — because every police
 * coordinate is published rather than derived — in having no accuracy to
 * qualify. They share the popup stylesheet, which is the part that was actually
 * common.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Layer, Popup, Source, useMap } from 'react-map-gl/mapbox'

import { BADGE_SIZE_BY_ZOOM, useStationBadge } from './stationBadges'
import { useStationReveal, withLatitude } from './useStationReveal'

import '../../pages/visuals/firestationpopup.css'


/** Named here so the dashboard can list it in interactiveLayerIds. */
export const POLICE_STATIONS_LAYER_ID = 'police-stations-dots'

/** Must outlast the close transition in firestationpopup.css. */
const CLOSE_MS = 150

/**
 * The rank of a site, as published. A district headquarters and a two-officer
 * post are both "police stations" and are not the same thing to a dispatcher.
 */
const KIND_LABEL: Record<string, string> = {
  district: 'מחוז',
  region: 'מרחב',
  station: 'תחנה',
  post: 'נקודת משטרה',
  base: 'בסיס',
  centre: 'מרכז שיטור',
}


type PoliceStationsLayerProps = {
  visible?: boolean
  onLoaded?: (counts: { located: number; total: number }) => void
}


type SelectedStation = {
  longitude: number
  latitude: number
  name: string
  kind: string
  city: string | null
  address: string | null
  phone: string | null
}


export type PoliceStationsCollection = GeoJSON.FeatureCollection & {
  located: number
  total: number
}


function PoliceStationsLayer({
  visible = true,
  onLoaded,
}: PoliceStationsLayerProps) {
  const [stations, setStations] = useState<PoliceStationsCollection | null>(null)
  const [selected, setSelected] = useState<SelectedStation | null>(null)
  const [closing, setClosing] = useState(false)
  const closeTimer = useRef<number | null>(null)
  const { current: map } = useMap()
  const badgeReady = useStationBadge(map, 'police-station-badge', '/Emblem_of_Israel_Police_Blue.svg', '#1d4ed8')
  const reveal = useStationReveal(visible, 1)

  // The reveal re-renders this component on every animation frame, and
  // withLatitude builds a new collection each time it runs. Without this the
  // GeoJSON source would be replaced sixty times a second.
  const data = useMemo(
    () => (stations ? withLatitude(stations) : null),
    [stations],
  )

  // Held for the length of the close transition; unmounting on the same frame
  // would leave nothing to animate.
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
    if (!visible || stations) return

    let cancelled = false

    fetch('/api/police-stations')
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status))
        return response.json()
      })
      .then((value: PoliceStationsCollection) => {
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

  useEffect(() => {
    if (!map || !visible) return

    const openPopup = (event: any) => {
      const feature = event.features?.[0]
      if (!feature) return

      const [longitude, latitude] = feature.geometry.coordinates
      cancelDismiss()
      setSelected({ longitude, latitude, ...feature.properties })
    }

    const enter = () => { map.getCanvas().style.cursor = 'pointer' }
    const leave = () => { map.getCanvas().style.cursor = '' }

    map.on('click', POLICE_STATIONS_LAYER_ID, openPopup)
    map.on('mouseenter', POLICE_STATIONS_LAYER_ID, enter)
    map.on('mouseleave', POLICE_STATIONS_LAYER_ID, leave)

    return () => {
      map.off('click', POLICE_STATIONS_LAYER_ID, openPopup)
      map.off('mouseenter', POLICE_STATIONS_LAYER_ID, enter)
      map.off('mouseleave', POLICE_STATIONS_LAYER_ID, leave)
      leave()
    }
  }, [map, visible, cancelDismiss])

  useEffect(() => {
    if (!visible) {
      setSelected(null)
      setClosing(false)
    }
  }, [visible])

  if (!reveal.mounted || !data || !badgeReady) {
    return null
  }

  return (
    <>
      <Source id="police-stations-source" type="geojson" data={data}>
        <Layer
          id={POLICE_STATIONS_LAYER_ID}
          type="symbol"
          layout={{
            'icon-image': 'police-station-badge',
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
              {KIND_LABEL[selected.kind] ?? selected.kind}
              {selected.city && ` · ${selected.city}`}
            </div>

            {selected.address && (
              <div className="station-card__address">{selected.address}</div>
            )}

            {selected.phone && (
              <div className="station-card__contact">
                <a href={`tel:${selected.phone.replace(/[\s-]/g, '')}`}>
                  {selected.phone}
                </a>
              </div>
            )}

            {/* No accuracy caveat, unlike the fire stations: the Israel Police
                publishes a coordinate per station, so there is nothing here
                that was inferred from an address. */}
            <div className="station-card__basis">
              <span className="station-card__dot station-card__dot--exact" />
              מיקום מדויק — מתוך נתוני משטרת ישראל
            </div>
          </div>
        </Popup>
      )}
    </>
  )
}

export default PoliceStationsLayer
