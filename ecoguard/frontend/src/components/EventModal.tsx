import { useEffect } from 'react'
import { classify, hazardOf } from './hazards'
import type {
  AirPollutionEvent,
  FireEvent,
  SharedEvent,
} from '../types/events'

function formatTimestamp(timestamp: string) {
  const value = new Date(timestamp)
  return Number.isNaN(value.getTime())
    ? timestamp
    : new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Jerusalem',
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(value)
}

function formatDistance(distance: number | null | undefined) {
  if (distance == null) return null
  return distance >= 1000
    ? `${(distance / 1000).toFixed(1)} km`
    : `${Math.round(distance)} m`
}

function formatDuration(seconds: number | null) {
  if (seconds == null) return null
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  return `${(seconds / 3600).toFixed(1)} hr`
}

function formatComponentName(component: string) {
  return component
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatUnavailableReason(reason: string) {
  return reason.replaceAll('_', ' ')
}

function compactAirPollutionLimitations(limitations: string[]) {
  const unique = new Map<string, string>()
  let hasMonitoringLocationLimitation = false

  for (const limitation of limitations) {
    const normalized = limitation.trim().replace(/\s+/g, ' ')
    const lower = normalized.toLowerCase()

    // These truths are already stated once beside the corresponding evidence.
    if (/transport|corridor|plume|downwind screening|sector geometry/.test(lower)) continue
    if (/population/.test(lower)) continue
    if (/\bp95\b|historically unusual|historical unusualness/.test(lower)) continue
    if (/unavailable:/.test(lower)) continue

    if (/monitoring location|emission source/.test(lower)) {
      hasMonitoringLocationLimitation = true
      continue
    }

    unique.set(lower, normalized)
  }

  if (hasMonitoringLocationLimitation) {
    unique.set(
      'monitoring-location-is-not-a-source',
      'The monitoring location is not a confirmed emission source.',
    )
  }

  return [...unique.values()]
}

function FireEventDetails({ event }: { event: FireEvent }) {
  const details = event.details
  const assessed = event.analysis_status === 'success' && details.risk_score !== null

  return (
    <>
      <dl className="event-modal__facts">
        <div><dt>Risk</dt><dd>{assessed ? `${details.risk_level} · ${details.risk_score}` : 'not assessed'}</dd></div>
        <div><dt>Detection confidence</dt><dd>{details.detection_confidence ?? '—'}</dd></div>
        <div><dt>Fire weather severity</dt><dd>{details.fire_weather_severity ?? '—'}</dd></div>
      </dl>

      {details.explanation && (
        <section className="event-modal__section">
          <h3>Assessment</h3>
          <p>{details.explanation}</p>
        </section>
      )}

      {details.primary_drivers.length > 0 && (
        <section className="event-modal__section">
          <h3>Primary drivers</h3>
          <ul>{details.primary_drivers.map((driver) => <li key={driver}>{driver}</li>)}</ul>
        </section>
      )}

      {details.response_actions.length > 0 && (
        <section className="event-modal__section">
          <h3>Response plan</h3>
          <ol className="event-modal__actions">
            {details.response_actions.map((action, index) => (
              <li key={`${action.responsible_unit}-${index}`}>
                {action.action}
                <span className="event-modal__timeframe">{action.timeframe}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {details.recommended_units.length > 0 && (
        <section className="event-modal__section">
          <h3>Recommended units</h3>
          <ul>{details.recommended_units.map((unit) => <li key={unit}>{unit}</li>)}</ul>
        </section>
      )}

      {details.evidence_gaps.length > 0 && (
        <section className="event-modal__section event-modal__section--gaps">
          <h3>Evidence gaps</h3>
          <ul>{details.evidence_gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>
        </section>
      )}

      {details.protocol_citations.length > 0 && (
        <section className="event-modal__section">
          <h3>Protocol citations</h3>
          {details.protocol_citations.map((citation) => (
            <blockquote key={citation.chunk_id} className="event-modal__citation">
              <p>“{citation.quoted_text}”</p>
              <footer>{citation.document_title ?? citation.chunk_id}</footer>
            </blockquote>
          ))}
        </section>
      )}
    </>
  )
}

function AirPollutionEventDetails({ event }: { event: AirPollutionEvent }) {
  const details = event.details
  const baseline = details.historical_baseline
  const ministry = details.ministry_aqi
  const transport = details.transport
  const population = details.population_within_screening_corridor
  const insideSettlements = details.relevant_settlements.filter(
    (settlement) => settlement.inside_transport_corridor,
  )
  const unavailableComponents = Array.from(
    new Map(
      details.unavailable_components.map((item) => [
        `${item.component}:${item.reason}`,
        item,
      ]),
    ).values(),
  )
  const compactLimitations = compactAirPollutionLimitations(details.limitations)

  return (
    <>
      <section className="event-modal__section">
        <h3>Measurement</h3>
        <dl className="event-modal__facts event-modal__facts--compact">
          <div><dt>Pollutant</dt><dd>{details.pollutant}</dd></div>
          <div><dt>Measured value</dt><dd>{details.measured_value} {details.unit}</dd></div>
          <div><dt>Station</dt><dd>{details.station.name ?? details.station.id}</dd></div>
          <div><dt>Observed</dt><dd>{formatTimestamp(details.observation_timestamp)}</dd></div>
        </dl>
      </section>

      <section className="event-modal__section">
        <h3>Historical baseline context</h3>
        {baseline ? (
          <>
            <p>
              Historical p95 for the matching baseline bucket: <strong>{baseline.p95} {details.unit}</strong>.
            </p>
            <p className="event-modal__semantic-note">
              Exceeding p95 means this observation is historically unusual for this station and time bucket. It is not a health threshold or health-severity rating.
            </p>
            <dl className="event-modal__facts event-modal__facts--compact">
              {baseline.month != null && <div><dt>Month</dt><dd>{baseline.month}</dd></div>}
              {baseline.hour != null && <div><dt>Hour</dt><dd>{String(baseline.hour).padStart(2, '0')}:00</dd></div>}
              {baseline.sample_count != null && <div><dt>Samples</dt><dd>{baseline.sample_count}</dd></div>}
              {baseline.baseline_family && <div><dt>Baseline family</dt><dd>{baseline.baseline_family}</dd></div>}
              {baseline.baseline_version_id != null && <div><dt>Version</dt><dd>{baseline.baseline_version_id}</dd></div>}
            </dl>
          </>
        ) : <p>Historical baseline evidence is unavailable.</p>}
      </section>

      <section className="event-modal__section">
        <h3>Ministry AQI</h3>
        {ministry ? (
          <dl className="event-modal__facts event-modal__facts--compact">
            <div><dt>Station index</dt><dd>{ministry.station_index}</dd></div>
            <div>
              <dt>Native category</dt>
              <dd>
                <span
                  className="event-modal__aqi-category"
                  style={ministry.category_color ? { '--aqi-color': ministry.category_color } as React.CSSProperties : undefined}
                >
                  {ministry.station_category}
                </span>
              </dd>
            </div>
            {ministry.pollutant_sub_index != null && <div><dt>Pollutant sub-index</dt><dd>{ministry.pollutant_sub_index}</dd></div>}
            <div><dt>Provider time</dt><dd>{formatTimestamp(ministry.provider_timestamp)}</dd></div>
          </dl>
        ) : <p>Ministry-native air-quality index evidence is unavailable.</p>}
      </section>

      <section className="event-modal__section">
        <h3>Wind evidence</h3>
        {details.wind ? (
          <dl className="event-modal__facts event-modal__facts--compact">
            <div><dt>Wind from</dt><dd>{details.wind.wind_from_direction_deg.toFixed(0)}°</dd></div>
            <div><dt>Speed</dt><dd>{details.wind.wind_speed_mps.toFixed(1)} m/s</dd></div>
            <div><dt>Source</dt><dd>{details.wind.provider_location_name ?? details.wind.provider}</dd></div>
            <div><dt>Evidence time</dt><dd>{formatTimestamp(details.wind.observed_or_valid_at)}</dd></div>
          </dl>
        ) : <p>Wind evidence is unavailable.</p>}
      </section>

      <section className="event-modal__section">
        <h3>Possible transport corridor</h3>
        {transport?.corridor ? (
          <>
            <p>The selected event’s backend-provided screening corridor is shown on the map.</p>
            <dl className="event-modal__facts event-modal__facts--compact">
              {transport.downwind_to_direction_deg != null && <div><dt>Downwind direction</dt><dd>{transport.downwind_to_direction_deg.toFixed(0)}°</dd></div>}
              {transport.max_screening_distance_m != null && <div><dt>Screening range</dt><dd>{formatDistance(transport.max_screening_distance_m)}</dd></div>}
              {transport.corridor_half_angle_deg != null && <div><dt>Half-angle</dt><dd>{transport.corridor_half_angle_deg}°</dd></div>}
            </dl>
          </>
        ) : <p>Transport corridor geometry is unavailable.</p>}
        <p className="event-modal__semantic-note">
          This is a possible transport screening corridor, not a confirmed plume, affected area, transport path, or evidence of exposure.
        </p>
      </section>

      <section className="event-modal__section">
        <h3>Relevant settlements</h3>
        {insideSettlements.length > 0 ? (
          <ul className="event-modal__settlements">
            {insideSettlements.map((settlement) => (
              <li key={settlement.id}>
                <strong>{settlement.name}</strong>
                {settlement.distance_m != null && <> · {formatDistance(settlement.distance_m)}</>}
                {settlement.transport_time?.status === 'estimated' && (
                  <> · screened transport time {formatDuration(settlement.transport_time.seconds)}</>
                )}
                <span>Possible downwind relevance only; exposure is not confirmed.</span>
              </li>
            ))}
          </ul>
        ) : <p>No settlements are identified inside the available screening corridor.</p>}
      </section>

      <section className="event-modal__section">
        <h3>Population within screening corridor</h3>
        {population ? (
          <>
            <p className="event-modal__population">{population.total_relevant_population.toLocaleString()}</p>
            <p>
              Estimated population geographically intersecting the screening corridor across {population.intersected_cell_count.toLocaleString()} population grid cells.
            </p>
          </>
        ) : <p>Geographic population screening is unavailable.</p>}
        {population && (
          <p className="event-modal__semantic-note">
            This is not an affected or exposed population count.
          </p>
        )}
      </section>

      {details.recommendations.length > 0 && (
        <section className="event-modal__section">
          <h3>Planner recommendations</h3>
          <ol className="event-modal__actions">
            {details.recommendations.map((action, index) => (
              <li key={`${action.responsible_authority_type}-${index}`}>
                <strong>{action.recommendation}</strong>
                <p>{action.rationale}</p>
                <span className="event-modal__timeframe">{action.timeframe}</span>
                <span className="event-modal__timeframe">{action.priority}</span>
                <span className="event-modal__action-owner">{action.responsible_authority_type} · {action.resource_type}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {details.trend !== null && (
        <section className="event-modal__section">
          <h3>Trend</h3>
          <p>{details.trend}</p>
        </section>
      )}

      {(unavailableComponents.length > 0 || compactLimitations.length > 0) && (
        <section className="event-modal__section event-modal__section--gaps">
          <h3>Evidence limitations and unavailable components</h3>
          <ul>
            {unavailableComponents.map((item) => (
              <li key={`${item.component}-${item.reason}`}>
                <strong>{formatComponentName(item.component)}:</strong>{' '}
                {formatUnavailableReason(item.reason)}
              </li>
            ))}
            {compactLimitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
          </ul>
        </section>
      )}

      {details.verified_references.length > 0 && (
        <section className="event-modal__section">
          <h3>Verified references</h3>
          {details.verified_references.map((reference) => (
            <blockquote key={reference.id} className="event-modal__citation">
              <p>“{reference.quoted_text}”</p>
              <footer>
                {reference.source_url ? (
                  <a href={reference.source_url} target="_blank" rel="noreferrer">{reference.document_title}</a>
                ) : reference.document_title}
              </footer>
            </blockquote>
          ))}
        </section>
      )}
    </>
  )
}

function EventModal({ event, onClose }: {
  event: SharedEvent
  onClose: () => void
}) {
  const hazard = hazardOf(event)
  const urgency = classify(event)

  useEffect(() => {
    const onKey = (keyboardEvent: KeyboardEvent) => {
      if (keyboardEvent.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="event-modal__backdrop" onClick={onClose} role="presentation">
      <div
        className="event-modal"
        style={{ '--hazard': hazard.color } as React.CSSProperties}
        role="dialog"
        aria-modal="true"
        aria-label={event.title}
        onClick={(clickEvent) => clickEvent.stopPropagation()}
      >
        <header className="event-modal__header">
          <div>
            <span className="event-modal__type">{hazard.label}</span>
            <span className={`event-modal__urgency event-modal__urgency--${urgency}`}>
              {urgency}
            </span>
          </div>
          <button type="button" className="event-modal__close" onClick={onClose}>Close</button>
        </header>

        <h2 className="event-modal__title">{event.title}</h2>
        <dl className="event-modal__facts">
          <div>
            <dt>{event.type === 'air_pollution' ? 'Monitoring location' : 'Location'}</dt>
            <dd>{event.latitude.toFixed(4)}, {event.longitude.toFixed(4)}</dd>
          </div>
          {event.observed_at && <div><dt>Observed</dt><dd>{formatTimestamp(event.observed_at)}</dd></div>}
        </dl>

        {event.description && <p className="event-modal__description">{event.description}</p>}
        {event.processing?.failure_reason && (
          <section className="event-modal__section event-modal__section--gaps">
            <h3>Latest processing status</h3>
            <p>
              {event.processing.failure_stage ?? 'processing'}: {event.processing.failure_reason}
            </p>
            {event.processing.using_last_successful_payload && (
              <p>Showing the last projectable event state; recommendations from an older plan are not shown.</p>
            )}
          </section>
        )}
        {event.type === 'fire' && <FireEventDetails event={event} />}
        {event.type === 'air_pollution' && <AirPollutionEventDetails event={event} />}
      </div>
    </div>
  )
}

export default EventModal
