import { Layer, Source } from 'react-map-gl/mapbox'
import type { AirPollutionEvent } from '../../types/events'

const CORRIDOR_SOURCE_ID = 'selected-air-pollution-corridor-source'
const CORRIDOR_FILL_ID = 'selected-air-pollution-corridor-fill'
const CORRIDOR_OUTLINE_ID = 'selected-air-pollution-corridor-outline'
const CENTERLINE_SOURCE_ID = 'selected-air-pollution-centerline-source'
const CENTERLINE_LAYER_ID = 'selected-air-pollution-centerline'

function AirPollutionCorridorLayer({ event }: { event: AirPollutionEvent }) {
  const corridor = event.details.transport?.corridor
  const centerline = event.details.transport?.centerline
  if (!corridor) return null

  const corridorFeature = {
    type: 'Feature' as const,
    properties: {
      event_id: event.id,
      semantics: 'possible_transport_screening_not_confirmed_plume_or_exposure',
    },
    geometry: corridor,
  }
  const centerlineFeature = centerline ? {
    type: 'Feature' as const,
    properties: { event_id: event.id },
    geometry: centerline,
  } : null

  return (
    <>
      <Source id={CORRIDOR_SOURCE_ID} type="geojson" data={corridorFeature}>
        <Layer
          id={CORRIDOR_FILL_ID}
          type="fill"
          paint={{
            'fill-color': '#a855f7',
            'fill-opacity': 0.18,
          }}
        />
        <Layer
          id={CORRIDOR_OUTLINE_ID}
          type="line"
          paint={{
            'line-color': '#a855f7',
            'line-opacity': 0.9,
            'line-width': 2,
            'line-dasharray': [3, 2],
          }}
        />
      </Source>

      {centerlineFeature && (
        <Source id={CENTERLINE_SOURCE_ID} type="geojson" data={centerlineFeature}>
          <Layer
            id={CENTERLINE_LAYER_ID}
            type="line"
            paint={{
              'line-color': '#f3e8ff',
              'line-opacity': 0.95,
              'line-width': 2,
            }}
          />
        </Source>
      )}

      <div className="air-pollution-corridor-legend">
        <span className="air-pollution-corridor-legend__swatch" />
        Possible transport screening
        <small>Not a confirmed plume or exposure area</small>
      </div>
    </>
  )
}

export default AirPollutionCorridorLayer
