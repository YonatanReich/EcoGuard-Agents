import { Fragment, type CSSProperties } from 'react'
import { Layer, Marker, Source } from 'react-map-gl/mapbox'
import type { AllocatedStation, FireEvent } from '../../types/events'

const RESOURCE_STYLE: Record<string, { color: string; label: string }> = {
  fire_department: { color: '#ef4444', label: 'F' },
  police: { color: '#3b82f6', label: 'P' },
  medical_services: { color: '#22c55e', label: 'M' },
}

function stationStyle(station: AllocatedStation) {
  return RESOURCE_STYLE[station.recommended_unit] ?? {
    color: '#f59e0b',
    label: 'R',
  }
}

function ResourceAllocationLayer({ event }: { event: FireEvent }) {
  const stations = event.details.resource_allocation?.stations ?? []

  return (
    <>
      {stations.map((station) => {
        const geometry = station.route?.geometry
        const style = stationStyle(station)
        const key = `${station.recommended_unit}-${station.database_id}`

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
                    'line-width': 4,
                    'line-opacity': 0.85,
                  }}
                />
              </Source>
            )}

            <Marker
              longitude={station.longitude}
              latitude={station.latitude}
              anchor="center"
            >
              <div
                className="allocation-station-marker"
                style={{ '--allocation-color': style.color } as CSSProperties}
                title={`${station.name} · ${station.distance_km?.toFixed(1) ?? '—'} km`}
                aria-label={`Assigned station: ${station.name}`}
              >
                {style.label}
              </div>
            </Marker>
          </Fragment>
        )
      })}

      {stations.length > 0 && (
        <div className="allocation-route-legend">
          Assigned stations and fastest routes
        </div>
      )}
    </>
  )
}

export default ResourceAllocationLayer
