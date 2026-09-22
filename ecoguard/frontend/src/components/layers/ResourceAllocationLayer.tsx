import { useEffect, useState, type CSSProperties } from 'react'
import { Layer, Marker, Popup, Source, useMap } from 'react-map-gl/mapbox'
import type { AllocatedStation, EarthquakeEvent, FireEvent, FloodEvent } from '../../types/events'

const NO_ALLOCATED_STATIONS: readonly AllocatedStation[] = Object.freeze([])

// The service's own emblem, the same badge the station layers and the
// "I want to see" bar use, ringed in the colour of its route.
const RESOURCE_STYLE: Record<string, { color: string; label: string; logo?: string }> = {
  fire_department: { color: '#ef4444', label: 'F', logo: '/FireDepIsrael.svg' },
  police: { color: '#3b82f6', label: 'P', logo: '/Emblem_of_Israel_Police_Blue.svg' },
  medical_services: { color: '#22c55e', label: 'M', logo: '/Mada_logo.svg' },
}

const RESOURCE_TYPE_LABEL: Record<string, string> = {
  fire_department: 'תחנת כיבוי',
  police: 'תחנת משטרה',
  medical_services: 'תחנת מד״א',
}

function stationStyle(station: AllocatedStation) {
  return RESOURCE_STYLE[station.recommended_unit] ?? {
    color: '#f59e0b',
    label: 'R',
  }
}

function stationKey(station: AllocatedStation) {
  return `${station.recommended_unit}-${station.database_id}`
}

function formatTravelTime(seconds: number | null | undefined) {
  if (seconds == null) return 'לא זמין'
  const totalMinutes = Math.max(1, Math.round(seconds / 60))
  if (totalMinutes < 60) return `${totalMinutes} דקות`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return minutes === 0
    ? `${hours} שעות`
    : `${hours} שעות ו-${minutes} דקות`
}

function formatStationDistance(distanceKm: number | null) {
  return distanceKm == null ? 'מרחק לא זמין' : `${distanceKm.toFixed(1)} ק״מ`
}

function ResourceAllocationLayer({
  event,
  onShowDirections,
  showLegend = false,
}: {
  event: FireEvent | EarthquakeEvent | FloodEvent
  onShowDirections: (stationKey: string) => void
  showLegend?: boolean
}) {
  const stations = event.details.resource_allocation?.stations ?? NO_ALLOCATED_STATIONS
  // Every event owns separate Mapbox source/layer IDs, allowing all active
  // allocation routes to be rendered at the same time.
  const layerSuffix = event.id.replace(/[^a-zA-Z0-9_-]/g, '_')
  const [selectedStationKey, setSelectedStationKey] = useState<string | null>(null)
  const selectedStation = stations.find(
    (station) => stationKey(station) === selectedStationKey,
  ) ?? null
  const routeFeatures = stations.flatMap((station) => {
    const geometry = station.route?.geometry
    if (!geometry) return []
    return [{
      type: 'Feature' as const,
      properties: {
        routeKey: stationKey(station),
        color: stationStyle(station).color,
      },
      geometry,
    }]
  })
  // Frame the whole dispatch when it appears: the event, every assigned
  // station and every route between them.
  const { current: map } = useMap()
  useEffect(() => {
    if (!map) return
    const points: number[][] = [
      [event.longitude, event.latitude],
      ...stations.map((station) => [station.longitude, station.latitude]),
      ...stations.flatMap((station) => station.route?.geometry?.coordinates ?? []),
    ]
    const longitudes = points.map(([longitude]) => longitude)
    const latitudes = points.map(([, latitude]) => latitude)
    map.fitBounds(
      [[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]],
      { padding: 80, duration: 1400, maxZoom: 14, essential: true },
    )
    // ponytail: frames once per event. Re-framing on every data refresh would
    // yank the camera away from wherever the operator has since moved it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, event.id])

  const offroadFeatures = stations.flatMap((station) => {
    const segment = station.route?.offroad_segment
    if (!segment?.geometry) return []
    return [{
      type: 'Feature' as const,
      properties: {
        routeKey: stationKey(station),
        color: stationStyle(station).color,
      },
      geometry: segment.geometry,
    }]
  })

  return (
    <>
      {routeFeatures.length > 0 && (
        <Source
          id={`resource-allocation-routes-${layerSuffix}`}
          type="geojson"
          data={{ type: 'FeatureCollection', features: routeFeatures }}
        >
          {/* The glow: a wide, blurred copy of each chosen road under its
              core line. Emissive so Standard's night lighting leaves it lit. */}
          <Layer
            id={`resource-allocation-route-glow-${layerSuffix}`}
            type="line"
            slot="top"
            layout={{
              'line-cap': 'round',
              'line-join': 'round',
            }}
            paint={{
              'line-color': ['get', 'color'],
              'line-width': 16,
              'line-blur': 12,
              'line-opacity': 0.55,
              'line-emissive-strength': 1,
            }}
          />

          <Layer
            id={`resource-allocation-background-routes-${layerSuffix}`}
            type="line"
            slot="top"
            filter={selectedStationKey
              ? ['!=', ['get', 'routeKey'], selectedStationKey]
              : ['has', 'routeKey']}
            layout={{
              'line-cap': 'round',
              'line-join': 'round',
            }}
            paint={{
              'line-color': ['get', 'color'],
              'line-width': selectedStationKey ? 3 : 4,
              'line-opacity': selectedStationKey ? 0.4 : 0.95,
              'line-emissive-strength': 1,
            }}
          />

          {selectedStationKey && (
            // This layer is declared after the background layer so Mapbox
            // always paints the selected route above every other route.
            <Layer
              id={`resource-allocation-selected-route-${layerSuffix}`}
              type="line"
              slot="top"
              filter={['==', ['get', 'routeKey'], selectedStationKey]}
              layout={{
                'line-cap': 'round',
                'line-join': 'round',
              }}
              paint={{
                'line-color': ['get', 'color'],
                'line-width': 7,
                'line-opacity': 1,
                'line-emissive-strength': 1,
              }}
            />
          )}
        </Source>
      )}

      {offroadFeatures.length > 0 && (
        <Source
          id={`resource-allocation-field-segments-${layerSuffix}`}
          type="geojson"
          data={{ type: 'FeatureCollection', features: offroadFeatures }}
        >
          <Layer
            id={`resource-allocation-field-segments-line-${layerSuffix}`}
            type="line"
            slot="top"
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            paint={{
              'line-color': ['get', 'color'],
              'line-width': selectedStationKey ? [
                'case',
                ['==', ['get', 'routeKey'], selectedStationKey],
                5,
                2,
              ] : 3,
              'line-opacity': selectedStationKey ? [
                'case',
                ['==', ['get', 'routeKey'], selectedStationKey],
                1,
                0.35,
              ] : 0.8,
              'line-dasharray': [2, 2],
              'line-emissive-strength': 1,
            }}
          />
        </Source>
      )}

      {stations.map((station) => {
        const style = stationStyle(station)
        const key = stationKey(station)
        const isSelected = selectedStationKey === key

        return (
          <Marker
            key={key}
            longitude={station.longitude}
            latitude={station.latitude}
            anchor="center"
          >
            <button
              type="button"
              className={`allocation-station-marker${isSelected ? ' allocation-station-marker--selected' : ''}`}
              style={{ '--allocation-color': style.color } as CSSProperties}
              title={`${station.name} · ${station.distance_km?.toFixed(1) ?? '—'} km`}
              aria-label={`Assigned station: ${station.name}`}
              onClick={(clickEvent) => {
                clickEvent.stopPropagation()
                setSelectedStationKey(key)
              }}
            >
              {style.logo ? <img src={style.logo} alt="" /> : style.label}
            </button>
          </Marker>
        )
      })}

      {selectedStation && (
        <Popup
          longitude={selectedStation.longitude}
          latitude={selectedStation.latitude}
          anchor="bottom"
          offset={24}
          closeOnClick={false}
          className="allocation-station-popup"
          onClose={() => setSelectedStationKey(null)}
        >
          <div className="allocation-station-popup__content" dir="rtl">
            <strong>
              {RESOURCE_TYPE_LABEL[selectedStation.recommended_unit] ?? 'תחנה'}:{' '}
              {selectedStation.name}
            </strong>
            <span>
              {selectedStation.route?.requires_field_access_confirmation
                ? 'זמן נסיעה עד נקודת סיום המסלול בכביש'
                : 'זמן נסיעה'}:{' '}
              {formatTravelTime(selectedStation.route?.duration_s)},{' '}
              {formatStationDistance(selectedStation.distance_km)}
            </span>
            {selectedStation.route?.requires_field_access_confirmation && (
              <span className="event-modal__allocation-warning">
                הקו המקווקו אל היעד הוא קטע שטח משוער; דרך הגישה וזמן ההתקדמות בו אינם מאומתים
              </span>
            )}
            <button
              type="button"
              onClick={() => onShowDirections(stationKey(selectedStation))}
            >
              הצג הוראות
            </button>
          </div>
        </Popup>
      )}

      {showLegend && stations.length > 0 && (
        <div className="allocation-route-legend">
          Assigned stations and fastest routes
        </div>
      )}

    </>
  )
}

export default ResourceAllocationLayer
