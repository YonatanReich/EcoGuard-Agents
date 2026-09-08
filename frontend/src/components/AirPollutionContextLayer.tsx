import { useState } from 'react'
import { Marker, Popup } from 'react-map-gl/maplibre'

import type { PollutionNearbyFeature } from '../types/airPollution'
import type { IncidentDetails } from '../types/incidents'
import { isAirPollutionEvent } from '../utils/airPollutionEvents'

import './air-pollution-map.css'

const PROXIMITY_LIMITATION = 'Proximity-based context. Exposure is not confirmed.'

function AirPollutionContextLayer({ event }: { event: IncidentDetails | null }) {
  const [selected, setSelected] = useState<PollutionNearbyFeature | null>(null)

  if (!isAirPollutionEvent(event)) return null

  const settlements = (event?.spatial_context?.nearby_settlements ?? []).filter(
    (item) => typeof item.latitude === 'number' && typeof item.longitude === 'number',
  )

  return (
    <>
      {settlements.map((settlement, index) => (
        <Marker
          key={`${settlement.osm_type ?? 'point'}-${settlement.osm_id ?? settlement.name ?? index}`}
          longitude={settlement.longitude as number}
          latitude={settlement.latitude as number}
          anchor="center"
        >
          <button
            type="button"
            className="pollution-settlement-marker"
            title={`${settlement.name ?? 'Unnamed settlement'} — nearby context only`}
            onClick={(click) => {
              click.stopPropagation()
              setSelected(settlement)
            }}
          >
            <span aria-hidden="true" />
          </button>
        </Marker>
      ))}
      {selected && typeof selected.latitude === 'number' && typeof selected.longitude === 'number' && (
        <Popup
          longitude={selected.longitude}
          latitude={selected.latitude}
          anchor="bottom"
          closeOnClick={false}
          offset={18}
          onClose={() => setSelected(null)}
        >
          <div className="pollution-map-popup">
            <strong>{selected.name ?? 'Unnamed settlement'}</strong>
            <span>Nearby settlement requiring attention</span>
            {typeof selected.distance_km === 'number' && <span>{selected.distance_km.toFixed(2)} km away</span>}
            <small>{PROXIMITY_LIMITATION}</small>
          </div>
        </Popup>
      )}
    </>
  )
}

export { PROXIMITY_LIMITATION }
export default AirPollutionContextLayer
