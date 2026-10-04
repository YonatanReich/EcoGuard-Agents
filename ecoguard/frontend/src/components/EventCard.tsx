import { hazardOf } from './hazards'
import HazardIcon from './HazardIcon'
import type { SharedEvent } from '../types/events'

function formatObservationTime(timestamp: string) {
  const value = new Date(timestamp)
  return Number.isNaN(value.getTime())
    ? timestamp
    : new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Jerusalem',
        dateStyle: 'short',
        timeStyle: 'short',
      }).format(value)
}

function EventCard({ event, onOpen, isSelected, onConfirm, isConfirming }: {
  event: SharedEvent
  onOpen: (event: SharedEvent) => void
  isSelected: boolean
  /** Omitted where confirming makes no sense, such as the demo feed. */
  onConfirm?: (event: SharedEvent) => void
  isConfirming?: boolean
}) {
  const hazard = hazardOf(event)
  // Absent on projections written before confirmation existed. Those were all
  // built from instrument data, so treating a missing value as confirmed keeps
  // old rows reading the way they always did rather than flagging them all.
  const unconfirmed = event.confirmation?.status === 'unconfirmed'
  const fire = event.type === 'fire' ? event.details : null
  const assessed = event.analysis_status === 'success' && fire?.risk_level != null
  const officialClassification = event.type === 'air_pollution'
    ? event.details.official_pollutant_classification?.classification
    : null
  const strongOfficialEmphasis = event.type === 'air_pollution'
    && event.details.publication_policy?.emphasis === 'strong'

  return (
    <article
      className={`event-card${isSelected ? ' event-card--selected' : ''}${strongOfficialEmphasis ? ' event-card--official-strong' : ''}${unconfirmed ? ' event-card--unconfirmed' : ''}`}
      style={{ '--hazard': hazard.color } as React.CSSProperties}
    >
    <button
      type="button"
      className="event-card__open"
      onClick={() => onOpen(event)}
      aria-label={`${hazard.label}: ${event.title}`}
    >
      <span className="event-card__type">
        <HazardIcon kind={event.type} />
        {hazard.label}
        {unconfirmed && (
          <span className="event-card__unconfirmed" title={event.confirmation?.detail ?? undefined}>
            Unconfirmed
          </span>
        )}
      </span>
      <span className="event-card__title">{event.title}</span>

      {event.type === 'earthquake' ? (
        <>
          <span className="event-card__measurement">
            Magnitude {event.details.magnitude.toFixed(1)} · depth {event.details.depth_km.toFixed(1)} km
          </span>
          <span className="event-card__meta">
            <span>Estimated Impact Area: {event.details.estimated_impact_radius_km} km</span>
            {event.observed_at && (
              <time dateTime={event.observed_at}>{formatObservationTime(event.observed_at)}</time>
            )}
          </span>
        </>
      ) : event.type === 'air_pollution' ? (
        <>
          <span className="event-card__measurement">
            {event.details.pollutant}: {event.details.measured_value} {event.details.unit}
          </span>
          <span className="event-card__station">
            {event.details.station.name ?? `Station ${event.details.station.id}`}
          </span>
          {officialClassification && (
            <span className="event-card__official-classification">
              Official pollutant index: {officialClassification.replaceAll('_', ' ')}
            </span>
          )}
          <span className="event-card__meta">
            <span>Advisory</span>
            <time dateTime={event.details.observation_timestamp}>
              {formatObservationTime(event.details.observation_timestamp)}
            </time>
          </span>
        </>
      ) : event.type === 'flood' ? (
        <>
          <span className="event-card__measurement">
            Severity {event.details.severity_level} · {event.details.return_period_label}
          </span>
          <span className="event-card__station">
            {event.details.risk_level && event.details.risk_score != null
              ? `Operational risk: ${event.details.risk_level} (${event.details.risk_score}/100)`
              : 'Operational risk not assessed'}
          </span>
          <span className="event-card__station">
            {event.details.sources.length} hydrometric station(s) ·{' '}
            {event.details.response_sites.length} road site(s)
          </span>
          <span className="event-card__meta">
            <span>{event.details.targeting_status.replaceAll('_', ' ')}</span>
            <span>{event.latitude.toFixed(3)}, {event.longitude.toFixed(3)}</span>
          </span>
        </>
      ) : (
        <>
          {fire?.dispatch?.grade != null && (
            <span className="event-card__grade">
              Grade {fire.dispatch.grade}
              {fire.dispatch.teams_required != null
                && ` · ${fire.dispatch.teams_required} teams`}
              {fire.dispatch.is_national_event && ' · national event'}
            </span>
          )}

          {/* Only ever shown when it was actually counted. A fire whose
              population could not be read must not render a zero. */}
          {fire?.people_in_spread != null && (
            <span className="event-card__measurement">
              {fire.people_in_spread.toLocaleString()} people in the forecast spread
            </span>
          )}

          {(fire?.evacuation?.length ?? 0) > 0 && (
            <span className="event-card__evacuation">
              {fire!.evacuation.filter((item) => item.priority === 'immediate').length > 0
                ? `Evacuate now: ${fire!.evacuation
                    .filter((item) => item.priority === 'immediate')
                    .map((item) => item.name_he ?? item.name)
                    .slice(0, 2)
                    .join(', ')}`
                : `${fire!.evacuation.length} settlement(s) to prepare`}
            </span>
          )}

          <span className="event-card__meta">
            {assessed && fire ? (
              <span className="event-card__score">
                {fire.risk_level} · {fire.risk_score}
              </span>
            ) : event.analysis_status === 'pending' ? (
              <span className="event-card__score event-card__score--pending">
                assessing risk…
              </span>
            ) : (
              <span className="event-card__score event-card__score--none">
                not assessed
              </span>
            )}
            {event.planning_status === 'pending' && (
              <span className="event-card__pending">plan being prepared…</span>
            )}
            {fire?.detection && fire.detection.verdict !== 'confirmed' && (
              <span className="event-card__detection">
                detection {fire.detection.verdict}
              </span>
            )}
            <span className="event-card__coords">
              {event.latitude.toFixed(3)}, {event.longitude.toFixed(3)}
            </span>
          </span>
        </>
      )}
    </button>

    {/* Outside the card's own button, because a button inside a button is
        invalid and the browser will not deliver this click. */}
    {unconfirmed && onConfirm && (
      <div className="event-card__confirm-row">
        <p className="event-card__confirm-note">
          Verify with the local authority and the responsible fire and police
          stations before treating this as an event.
        </p>
        <button
          type="button"
          className="event-card__confirm"
          disabled={isConfirming}
          onClick={() => onConfirm(event)}
        >
          {isConfirming ? 'Confirming…' : 'Mark as confirmed'}
        </button>
      </div>
    )}
    </article>
  )
}

export default EventCard
