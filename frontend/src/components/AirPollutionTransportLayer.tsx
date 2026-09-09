import { useState } from 'react'
import { Layer, Marker, Popup, Source } from 'react-map-gl/maplibre'

import type { AirPollutionTransportSettlement } from '../types/airPollution'
import type { IncidentDetails } from '../types/incidents'
import { eventSelectionKey } from '../utils/airPollutionEvents'
import { transportOutputForEvent } from '../utils/airPollutionTransport'
import {
  TRANSPORT_SCREENING_SUMMARY,
  formatTransportAngle,
  formatTransportDistance,
  formatTransportDuration,
  transportExclusionReasonLabel,
} from '../utils/airPollutionTransportPresentation'

import './air-pollution-map.css'

type SelectedSettlement = {
  eventKey: string
  settlement: AirPollutionTransportSettlement
}

function AirPollutionTransportLayer({ event }: { event: IncidentDetails | null }) {
  const [selection, setSelection] = useState<SelectedSettlement | null>(null)
  const transport = transportOutputForEvent(event)
  if (!transport || !event) return null

  const eventKey = [
    eventSelectionKey(event),
    event.anomaly?.detection_id ?? 'no-detection-id',
    event.anomaly?.observed_at ?? 'no-observation-time',
    transport.origin.coordinates.join(','),
  ].join(':')
  const selected = selection?.eventKey === eventKey ? selection.settlement : null
  const corridorFeature = {
    type: 'Feature' as const,
    properties: { kind: 'estimated_transport_screening_corridor' },
    geometry: transport.corridor_polygon!,
  }
  const centerlineFeature = {
    type: 'Feature' as const,
    properties: { kind: 'potential_atmospheric_transport_direction' },
    geometry: transport.centerline!,
  }

  return (
    <>
      <Source
        id="air-pollution-transport-corridor-source"
        type="geojson"
        data={corridorFeature}
      >
        <Layer
          id="air-pollution-transport-corridor-fill"
          type="fill"
          paint={{
            'fill-color': '#7c3aed',
            'fill-opacity': 0.16,
          }}
        />
        <Layer
          id="air-pollution-transport-corridor-outline"
          type="line"
          paint={{
            'line-color': '#6d28d9',
            'line-opacity': 0.82,
            'line-width': 2,
            'line-dasharray': [2, 2],
          }}
        />
      </Source>

      <Source
        id="air-pollution-transport-centerline-source"
        type="geojson"
        data={centerlineFeature}
      >
        <Layer
          id="air-pollution-transport-centerline"
          type="line"
          paint={{
            'line-color': '#5b21b6',
            'line-opacity': 0.95,
            'line-width': 3,
          }}
        />
      </Source>

      {(transport.settlements ?? []).map((settlement) => {
        const [longitude, latitude] = settlement.point.coordinates
        return (
          <Marker
            key={settlement.settlement_id}
            longitude={longitude}
            latitude={latitude}
            anchor="center"
          >
            <button
              type="button"
              className={settlement.inside_transport_corridor
                ? 'pollution-transport-settlement pollution-transport-settlement--inside'
                : 'pollution-transport-settlement pollution-transport-settlement--outside'}
              title={settlement.inside_transport_corridor
                ? `${settlement.name} — potentially downwind settlement`
                : `${settlement.name} — outside transport screening corridor`}
              onClick={(click) => {
                click.stopPropagation()
                setSelection({ eventKey, settlement })
              }}
            >
              <span aria-hidden="true" />
            </button>
          </Marker>
        )
      })}

      {selected && (
        <Popup
          longitude={selected.point.coordinates[0]}
          latitude={selected.point.coordinates[1]}
          anchor="bottom"
          closeOnClick={false}
          offset={16}
          onClose={() => setSelection(null)}
        >
          <div className="pollution-map-popup">
            <strong>{selected.name}</strong>
            <span>{selected.inside_transport_corridor
              ? 'Potentially downwind settlement'
              : 'Outside the current screening corridor'}</span>
            {selected.rank != null && (
              <span>Geometric downwind relevance rank: #{selected.rank}</span>
            )}
            {!selected.inside_transport_corridor
              && transportExclusionReasonLabel(selected.exclusion_reason) && (
              <span>{transportExclusionReasonLabel(selected.exclusion_reason)}</span>
            )}
            <dl className="pollution-map-popup__metrics">
              <div>
                <dt>Distance from analysis origin</dt>
                <dd>{formatTransportDistance(selected.geodesic_distance_m)}</dd>
              </div>
              <div>
                <dt>Angular difference</dt>
                <dd>{formatTransportAngle(selected.angular_difference_deg)}</dd>
              </div>
              <div>
                <dt>Along-wind distance</dt>
                <dd>{formatTransportDistance(selected.along_wind_distance_m)}</dd>
              </div>
              <div>
                <dt>Crosswind distance</dt>
                <dd>{formatTransportDistance(selected.crosswind_distance_m)}</dd>
              </div>
              <div>
                <dt>Screening transport duration</dt>
                <dd>{formatTransportDuration(selected.kinematic_advection_time_seconds)}</dd>
              </div>
            </dl>
            <small>{TRANSPORT_SCREENING_SUMMARY}</small>
          </div>
        </Popup>
      )}
    </>
  )
}

export default AirPollutionTransportLayer
