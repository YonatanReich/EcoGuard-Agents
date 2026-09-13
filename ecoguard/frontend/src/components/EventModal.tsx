/**
 * EventModal — the full record for one event.
 *
 * Opened from either the card or the map marker, so both routes land on the
 * same view. Shows the detection evidence, the risk assessment, the response
 * plan and the protocol citations as separate sections, because they are
 * separate claims made by separate stages — collapsing them would hide which
 * part of the pipeline said what.
 */

import { useEffect } from 'react'
import { classify, hazardOf } from './hazards'
import type { RiskEvent } from '../pages/Dashboard'


function EventModal({ event, onClose }: {
  event: RiskEvent
  onClose: () => void
}) {
  const hazard = hazardOf(event)
  const urgency = classify(event)
  const assessed = event.analysis_status === 'success' && event.risk_score !== null

  // Escape closes. Without it the only way out is the button, which is a trap
  // for keyboard users.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
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
        // Clicks inside must not reach the backdrop's close handler.
        onClick={(e) => e.stopPropagation()}
      >

        <header className="event-modal__header">
          <div>
            <span className="event-modal__type">{hazard.label}</span>
            <span className={`event-modal__urgency event-modal__urgency--${urgency}`}>
              {urgency}
            </span>
          </div>
          <button type="button" className="event-modal__close" onClick={onClose}>
            Close
          </button>
        </header>

        <h2 className="event-modal__title">{event.title}</h2>

        <dl className="event-modal__facts">
          <div><dt>Location</dt><dd>{event.latitude.toFixed(4)}, {event.longitude.toFixed(4)}</dd></div>
          <div><dt>Risk</dt><dd>{assessed ? `${event.risk_level} · ${event.risk_score}` : 'not assessed'}</dd></div>
          <div><dt>Detection confidence</dt><dd>{event.detection_confidence ?? '—'}</dd></div>
          <div><dt>Fire weather severity</dt><dd>{event.fire_weather_severity ?? '—'}</dd></div>
        </dl>

        {event.explanation && (
          <section className="event-modal__section">
            <h3>Assessment</h3>
            <p>{event.explanation}</p>
          </section>
        )}

        {event.primary_drivers.length > 0 && (
          <section className="event-modal__section">
            <h3>Primary drivers</h3>
            <ul>{event.primary_drivers.map((d) => <li key={d}>{d}</li>)}</ul>
          </section>
        )}

        {event.response_actions.length > 0 && (
          <section className="event-modal__section">
            <h3>Response plan</h3>
            <ol className="event-modal__actions">
              {event.response_actions.map((action, index) => (
                <li key={index}>
                  {action.action}
                  {action.timeframe && (
                    <span className="event-modal__timeframe">{action.timeframe}</span>
                  )}
                </li>
              ))}
            </ol>
          </section>
        )}

        {event.recommended_units.length > 0 && (
          <section className="event-modal__section">
            <h3>Recommended units</h3>
            <ul>{event.recommended_units.map((u) => <li key={u}>{u}</li>)}</ul>
          </section>
        )}

        {/* Stated, not hidden: what the model could not determine is part of
            the assessment, and omitting it would overstate confidence. */}
        {event.evidence_gaps.length > 0 && (
          <section className="event-modal__section event-modal__section--gaps">
            <h3>Evidence gaps</h3>
            <ul>{event.evidence_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
          </section>
        )}

        {event.protocol_citations.length > 0 && (
          <section className="event-modal__section">
            <h3>Protocol citations</h3>
            {event.protocol_citations.map((citation) => (
              <blockquote key={citation.chunk_id} className="event-modal__citation">
                <p>“{citation.quoted_text}”</p>
                <footer>{citation.document_title ?? citation.chunk_id}</footer>
              </blockquote>
            ))}
          </section>
        )}

      </div>
    </div>
  )
}

export default EventModal
