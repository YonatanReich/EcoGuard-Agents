import { Layer, Marker, Source } from 'react-map-gl/mapbox'
import type { FireEvent } from '../../types/events'

/**
 * The forecast spread of one fire: two rings and the settlements in them.
 *
 * Two extents rather than one. `likely` is the forecast wind; `possible` is the
 * union of a wind-error ensemble, and it is always the larger. Drawing only the
 * first understates the question an operator is actually asking, and drawing
 * them identically implies a confidence the second one does not have — so the
 * possible ring is dashed and faint, the likely ring solid.
 *
 * Painted beneath the settlement and station markers deliberately: the rings
 * are context for the places, not the subject.
 */

const LIKELY = '#dc2626'
const POSSIBLE = '#f59e0b'

const EXPOSURE_COLOR: Record<string, string> = {
  burning: '#7f1d1d',
  likely: LIKELY,
  possible: POSSIBLE,
}

function formatArrival(minutes: number | null) {
  if (minutes == null) return null
  if (minutes < 90) return `${Math.round(minutes)} min`
  return `${(minutes / 60).toFixed(1)} h`
}

function FireSpreadLayer({ event }: { event: FireEvent }) {
  const spread = event.details.spread
  if (!spread) return null

  const settlements = event.details.exposed_settlements

  return (
    <>
      {/* Possible first, so the likely ring paints over it rather than
          under it — otherwise the wider, less certain extent hides the one
          the forecast actually predicts. */}
      {spread.possible && (
        <Source
          id={`fire-possible-${event.id}`}
          type="geojson"
          data={{ type: 'Feature', properties: {}, geometry: spread.possible }}
        >
          <Layer
            id={`fire-possible-fill-${event.id}`}
            type="fill"
            paint={{ 'fill-color': POSSIBLE, 'fill-opacity': 0.1 }}
          />
          <Layer
            id={`fire-possible-line-${event.id}`}
            type="line"
            paint={{
              'line-color': POSSIBLE,
              'line-width': 1.5,
              'line-dasharray': [3, 2],
              'line-opacity': 0.75,
            }}
          />
        </Source>
      )}

      {spread.likely && (
        <Source
          id={`fire-likely-${event.id}`}
          type="geojson"
          data={{ type: 'Feature', properties: {}, geometry: spread.likely }}
        >
          <Layer
            id={`fire-likely-fill-${event.id}`}
            type="fill"
            paint={{ 'fill-color': LIKELY, 'fill-opacity': 0.22 }}
          />
          <Layer
            id={`fire-likely-line-${event.id}`}
            type="line"
            paint={{ 'line-color': LIKELY, 'line-width': 2.2 }}
          />
        </Source>
      )}

      {/* The origin, and which way the head is running. */}
      <Marker latitude={event.latitude} longitude={event.longitude} anchor="center">
        <div
          className="fire-spread__origin"
          title={
            spread.heading_compass
              ? `Running ${spread.heading_compass} at ${spread.head_rate_m_per_min} m/min`
              : 'Fire origin'
          }
          style={{ transform: `rotate(${spread.heading_deg ?? 0}deg)` }}
        >
          <span className="fire-spread__arrow">▲</span>
        </div>
      </Marker>

      {settlements.map((settlement) => (
        <Marker
          key={`${event.id}-${settlement.name}`}
          latitude={event.latitude}
          longitude={event.longitude}
          anchor="center"
          style={{ display: 'none' }}
        >
          {/* Settlement positions are not carried on the event — the analyser
              reports exposure and distance, not coordinates. Names are listed
              in the card and modal instead of guessed onto the map, which
              would put a label somewhere the settlement is not. */}
          <span />
        </Marker>
      ))}

      <div className="fire-spread__legend">
        <span>
          <i style={{ background: LIKELY }} /> likely extent
          {spread.horizon_minutes != null
            && ` · ${Math.round(spread.horizon_minutes / 60)} h`}
        </span>
        <span>
          <i className="dashed" style={{ borderColor: POSSIBLE }} /> possible on a
          wind shift
        </span>
        {settlements.slice(0, 4).map((settlement) => (
          <span key={settlement.name} className="fire-spread__settlement">
            <i style={{ background: EXPOSURE_COLOR[settlement.exposure] }} />
            {settlement.name}
            {formatArrival(settlement.arrival_minutes)
              && ` · ${formatArrival(settlement.arrival_minutes)}`}
          </span>
        ))}
      </div>
    </>
  )
}

export default FireSpreadLayer
