import { Fragment, useState, type CSSProperties } from 'react'
import { Layer, Marker, Popup, Source } from 'react-map-gl/mapbox'
import type { AllocatedStation, FireEvent } from '../../types/events'

const RESOURCE_STYLE: Record<string, { color: string; label: string }> = {
  fire_department: { color: '#ef4444', label: 'F' },
  police: { color: '#3b82f6', label: 'P' },
  medical_services: { color: '#22c55e', label: 'M' },
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

function formatEta(timestamp: string | null | undefined) {
  if (!timestamp) return 'לא זמין'
  const value = new Date(timestamp)
  if (Number.isNaN(value.getTime())) return timestamp
  return new Intl.DateTimeFormat('he-IL', {
    timeZone: 'Asia/Jerusalem',
    hour: '2-digit',
    minute: '2-digit',
  }).format(value)
}

function formatStationDistance(distanceKm: number | null) {
  return distanceKm == null ? 'מרחק לא זמין' : `${distanceKm.toFixed(1)} ק״מ`
}

function ResourceAllocationLayer({
  event,
  onShowDirections,
}: {
  event: FireEvent
  onShowDirections: (stationKey: string) => void
}) {
  const stations = event.details.resource_allocation?.stations ?? []
  const [selectedStationKey, setSelectedStationKey] = useState<string | null>(null)
  const selectedStation = stations.find(
    (station) => stationKey(station) === selectedStationKey,
  ) ?? null

  return (
    <>
      {stations.map((station) => {
        const geometry = station.route?.geometry
        const style = stationStyle(station)
        const key = stationKey(station)
        const isSelected = selectedStationKey === key
        const isDimmed = selectedStationKey !== null && !isSelected

        return (
          <Fragment key={key}>
            {geometry && (
              <Source
                id={`allocation-route-source-${key}`}
                type="geojson"
                data={{
                  type: 'Feature',
                  properties: {},
                  geometry,
                }}
              >
                <Layer
                  id={`allocation-route-${key}`}
                  type="line"
                  slot="top"
                  paint={{
                    'line-color': style.color,
                    'line-width': isSelected ? 7 : 4,
                    'line-opacity': isDimmed ? 0.12 : isSelected ? 1 : 0.85,
                  }}
                />
              </Source>
            )}

            <Marker
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
                {style.label}
              </button>
            </Marker>
          </Fragment>
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
              זמן הגעה משוער: {formatEta(selectedStation.route?.estimated_arrival_at)},{' '}
              {formatStationDistance(selectedStation.distance_km)}
            </span>
            <button
              type="button"
              onClick={() => onShowDirections(stationKey(selectedStation))}
            >
              הצג הוראות
            </button>
          </div>
        </Popup>
      )}

      {stations.length > 0 && (
        <div className="allocation-route-legend">
          Assigned stations and fastest routes
        </div>
      )}
    </>
  )
}

export default ResourceAllocationLayer
