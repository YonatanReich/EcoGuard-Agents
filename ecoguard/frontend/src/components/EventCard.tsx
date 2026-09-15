/**
 * EventCard — one event, compact, in the emergency or advisory panel.
 *
 * Summary only. Everything else is in the modal, so a panel of twenty events
 * stays scannable — an operator reads these to decide what to open, not to
 * learn the details.
 */

import { hazardOf } from './hazards'
import type { RiskEvent } from '../pages/Dashboard'


function EventCard({ event, onOpen, isSelected }: {
  event: RiskEvent
  onOpen: (event: RiskEvent) => void
  isSelected: boolean
}) {
  const hazard = hazardOf(event)
  const assessed = event.analysis_status === 'success' && event.risk_score !== null

  return (
    <button
      type="button"
      className={`event-card${isSelected ? ' event-card--selected' : ''}`}
      // The hazard colour is set here and read by CSS, so the card, the legend
      // swatch and the map marker cannot disagree.
      style={{ '--hazard': hazard.color } as React.CSSProperties}
      onClick={() => onOpen(event)}
      aria-label={`${hazard.label}: ${event.title}`}
    >
      <span className="event-card__type">{hazard.label}</span>

      <span className="event-card__title">{event.title}</span>

      <span className="event-card__meta">
        {assessed ? (
          <span className="event-card__score">
            {event.risk_level} · {event.risk_score}
          </span>
        ) : (
          // An unassessed event says so. A default "low" would read as an
          // all-clear that nothing in the pipeline actually claimed.
          <span className="event-card__score event-card__score--none">
            not assessed
          </span>
        )}
        <span className="event-card__coords">
          {event.latitude.toFixed(3)}, {event.longitude.toFixed(3)}
        </span>
      </span>
    </button>
  )
}

export default EventCard
