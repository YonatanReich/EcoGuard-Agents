/**
 * MdaStationsLayer — every Magen David Adom station, badged on the map.
 *
 * Reads /api/mda-stations, which serves MDA's own roster out of our
 * mda_stations table. Static reference data, fetched once when switched on.
 *
 * Marked with the Magen David Adom emblem on a white disc inside a red ring,
 * the same badge shape the other two services use.
 *
 * MDA publishes no coordinates, so — like the fire stations and unlike the
 * police — a dot is only as good as what placed it. Stations positioned from an
 * address rather than a mapped building are faded, and the popup says which.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Layer, Popup, Source, useMap } from 'react-map-gl/mapbox'

import { BADGE_SIZE_BY_ZOOM, useStationBadge } from './stationBadges'
import { useStationReveal, withLatitude } from './useStationReveal'

import '../../pages/visuals/firestationpopup.css'


/** Named here so the dashboard can list it in interactiveLayerIds. */
export const MDA_STATIONS_LAYER_ID = 'mda-stations-dots'

/** Must outlast the close animation in firestationpopup.css. */
const CLOSE_MS = 150


/**
 * What a dot's position is derived from. Only "building" is the station itself,
 * matched to the mapped ambulance station in OpenStreetMap. The rest come from
 * the roster's published address, and "city" is the town centroid.
 */
const POSITION_BASIS: Record<string, { label: string; tone: string }> = {
  building: { label: 'מיקום מדויק — מבנה התחנה', tone: 'exact' },
  street: { label: 'מיקום מקורב — רחוב התחנה', tone: 'near' },
  neighborhood: { label: 'מיקום מקורב — שכונה', tone: 'near' },
  city: { label: 'מיקום משוער — מרכז היישוב', tone: 'rough' },
}


type MdaStationsLayerProps = {
  visible?: boolean
  onLoaded?: (counts: { located: number; total: number }) => void
}


type SelectedStation = {
  longitude: number
  latitude: number
  name: string
  locality: string | null
  address: string | null
  precision: string | null
}


export type MdaStationsCollection = GeoJSON.FeatureCollection & {
  located: number
  total: number
}


function MdaStationsLayer({ visible = true, onLoaded }: MdaStationsLayerProps) {
  const [stations, setStations] = useState<MdaStationsCollection | null>(null)
  const [selected, setSelected] = useState<SelectedStation | null>(null)
  const [closing, setClosing] = useState(false)
  const closeTimer = useRef<number | null>(null)
  const { current: map } = useMap()
  const badgeReady = useStationBadge(map, 'mda-station-badge', '/Mada_logo.svg', '#dc2626')
  const reveal = useStationReveal(visible, ['case', ['==', ['get', 'precision'], 'city'], 0.45, 1])

  // The reveal re-renders this component on every animation frame, and
  // withLatitude builds a new collection each time it runs. Without this the
  // GeoJSON source would be replaced sixty times a second.
  const data = useMemo(
    () => (stations ? withLatitude(stations) : null),
    [stations],
  )

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

    fetch('/api/mda-stations')
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status))
        return response.json()
      })
      .then((value: MdaStationsCollection) => {
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

    map.on('click', MDA_STATIONS_LAYER_ID, openPopup)
    map.on('mouseenter', MDA_STATIONS_LAYER_ID, enter)
    map.on('mouseleave', MDA_STATIONS_LAYER_ID, leave)

    return () => {
      map.off('click', MDA_STATIONS_LAYER_ID, openPopup)
      map.off('mouseenter', MDA_STATIONS_LAYER_ID, enter)
      map.off('mouseleave', MDA_STATIONS_LAYER_ID, leave)
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

  const basis = POSITION_BASIS[selected?.precision ?? ''] ?? {
    label: 'מיקום משוער',
    tone: 'rough',
  }

  return (
    <>
      <Source id="mda-stations-source" type="geojson" data={data}>
        <Layer
          id={MDA_STATIONS_LAYER_ID}
          type="symbol"
          layout={{
            'icon-image': 'mda-station-badge',
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
              מגן דוד אדום
              {selected.locality && ` · ${selected.locality}`}
            </div>

            {selected.address && (
              <div className="station-card__address">{selected.address}</div>
            )}

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

export default MdaStationsLayer
