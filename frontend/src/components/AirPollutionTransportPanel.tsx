import type { AirPollutionTransportSettlement } from '../types/airPollution'
import type { IncidentDetails } from '../types/incidents'
import { isAirPollutionEvent } from '../utils/airPollutionEvents'
import { transportOutputForEvent } from '../utils/airPollutionTransport'
import {
  TRANSPORT_PRESENTATION_LIMITATIONS,
  TRANSPORT_SCREENING_SUMMARY,
  formatTransportAngle,
  formatTransportDistance,
  formatTransportDuration,
  inCorridorRankedSettlements,
  outsideCorridorSettlements,
  settlementCandidateScopeLimitation,
  transportCorridorMethodLabel,
  transportExclusionReasonLabel,
} from '../utils/airPollutionTransportPresentation'

function RankedSettlementRow({
  settlement,
}: {
  settlement: AirPollutionTransportSettlement
}) {
  return (
    <li className="pollution-transport-panel__settlement">
      <div className="pollution-transport-panel__settlement-heading">
        <strong>#{settlement.rank} {settlement.name}</strong>
        <span>Potentially downwind</span>
      </div>
      <dl className="pollution-transport-panel__metrics">
        <div>
          <dt>Distance</dt>
          <dd>{formatTransportDistance(settlement.geodesic_distance_m)}</dd>
        </div>
        <div>
          <dt>Angular difference</dt>
          <dd>{formatTransportAngle(settlement.angular_difference_deg)}</dd>
        </div>
        <div>
          <dt>Screening duration</dt>
          <dd>{formatTransportDuration(settlement.kinematic_advection_time_seconds)}</dd>
        </div>
      </dl>
      <div className="pollution-transport-panel__components">
        <span>Along-wind: {formatTransportDistance(settlement.along_wind_distance_m)}</span>
        <span>Crosswind: {formatTransportDistance(settlement.crosswind_distance_m)}</span>
      </div>
    </li>
  )
}

function OutsideSettlementRow({
  settlement,
}: {
  settlement: AirPollutionTransportSettlement
}) {
  const reason = transportExclusionReasonLabel(settlement.exclusion_reason)
  return (
    <li>
      <strong>{settlement.name}</strong>
      <span>{reason ?? 'Outside the current screening corridor'}</span>
      <small>
        Distance {formatTransportDistance(settlement.geodesic_distance_m)} · angle{' '}
        {formatTransportAngle(settlement.angular_difference_deg)}
      </small>
    </li>
  )
}

function AirPollutionTransportPanel({ event }: { event: IncidentDetails | null }) {
  if (!isAirPollutionEvent(event) || !event) return null

  const transport = transportOutputForEvent(event)
  if (!transport) {
    return (
      <section
        className="pollution-transport-panel pollution-transport-panel--unavailable"
        aria-label="Air pollution transport screening"
      >
        <strong>Atmospheric transport screening unavailable</strong>
        <p>Atmospheric transport screening is currently unavailable for this event.</p>
      </section>
    )
  }

  const settlements = transport.settlements ?? []
  const ranked = inCorridorRankedSettlements(settlements)
  const outside = outsideCorridorSettlements(settlements)
  const limitations = Array.from(new Set([
    ...TRANSPORT_PRESENTATION_LIMITATIONS,
    settlementCandidateScopeLimitation(event.spatial_context?.lookup_radius_km),
    ...transport.limitations,
  ]))

  return (
    <section
      className="pollution-transport-panel"
      aria-label="Air pollution geometric downwind relevance"
    >
      <header>
        <span>Air pollution transport</span>
        <h3>Geometric downwind relevance</h3>
        <p>{TRANSPORT_SCREENING_SUMMARY}</p>
      </header>

      <dl className="pollution-transport-panel__summary">
        <div>
          <dt>Downwind direction</dt>
          <dd>{formatTransportAngle(transport.downwind_to_direction_deg!)}</dd>
        </div>
        <div>
          <dt>Potentially downwind</dt>
          <dd>{ranked.length} of {settlements.length} candidates</dd>
        </div>
        <div>
          <dt>Corridor method</dt>
          <dd>{transportCorridorMethodLabel(transport.corridor_method)}</dd>
        </div>
        <div>
          <dt>Configured range</dt>
          <dd>{formatTransportDistance(transport.max_screening_distance_m)}</dd>
        </div>
        <div>
          <dt>Corridor half-angle</dt>
          <dd>{formatTransportAngle(transport.corridor_half_angle_deg)}</dd>
        </div>
      </dl>

      <p className="pollution-transport-panel__ranking-note">
        Backend ranking prioritizes forward/downwind position, then angular
        alignment, distance, and a stable tie-breaker. This ordering describes
        geometry only and does not indicate hazard severity.
      </p>

      <div className="pollution-transport-panel__scroll">
        <section aria-labelledby="downwind-ranking-title">
          <h4 id="downwind-ranking-title">Potentially downwind settlements</h4>
          {ranked.length > 0 ? (
            <ol className="pollution-transport-panel__ranking">
              {ranked.map((settlement) => (
                <RankedSettlementRow
                  key={settlement.settlement_id}
                  settlement={settlement}
                />
              ))}
            </ol>
          ) : (
            <p className="pollution-transport-panel__empty">
              No available settlement candidate is inside the current screening
              corridor. This does not establish that no farther settlement is relevant.
            </p>
          )}
        </section>

        {outside.length > 0 && (
          <details className="pollution-transport-panel__details">
            <summary>Outside the current screening corridor ({outside.length})</summary>
            <ul className="pollution-transport-panel__outside">
              {outside.map((settlement) => (
                <OutsideSettlementRow
                  key={settlement.settlement_id}
                  settlement={settlement}
                />
              ))}
            </ul>
          </details>
        )}

        <details className="pollution-transport-panel__details" open>
          <summary>Limitations</summary>
          <ul className="pollution-transport-panel__limitations">
            {limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </details>
      </div>
    </section>
  )
}

export default AirPollutionTransportPanel
