import { useState } from 'react'
import { HAZARDS } from './hazards'
import type { WeakEvent } from '../types/weakEvents'

/**
 * A report nobody has corroborated.
 *
 * Deliberately not an EventCard with a flag. The two say different things —
 * "this is happening" and "somebody said this is happening" — and the card is
 * the last place that distinction can be made before an operator acts on it.
 * A dashed border and a badge, rather than a subtler cue, because the whole
 * point is that it must not be mistaken for the other one at a glance.
 */

function remaining(seconds: number): string {
  if (seconds <= 0) return 'expiring'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min left`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m left`
}

function sourceLabel(tier: string): string {
  // The tier is shown because "two local channels said so" and "the police
  // said so" are different claims, and the operator is the one deciding.
  if (tier === 'authority') return 'authority'
  if (tier === 'media') return 'media'
  return 'unofficial'
}

function WeakEventCard({ weakEvent, onDecide, operator }: {
  weakEvent: WeakEvent
  onDecide: (id: string, decision: 'confirm' | 'dismiss') => Promise<void>
  operator: string
}) {
  const [busy, setBusy] = useState<'confirm' | 'dismiss' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const hazard = HAZARDS[weakEvent.hazard === 'air_quality' ? 'air_pollution' : weakEvent.hazard]

  const decide = async (decision: 'confirm' | 'dismiss') => {
    setBusy(decision)
    setError(null)
    try {
      await onDecide(weakEvent.id, decision)
    } catch {
      setError('Could not record that. Try again.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <article
      className="weak-event-card"
      style={{ '--hazard': hazard.color } as React.CSSProperties}
      aria-label={`Unverified ${hazard.label} report at ${weakEvent.location_text ?? 'an unnamed location'}`}
    >
      <header className="weak-event-card__header">
        <span className="weak-event-card__type">{hazard.label}</span>
        <span className="weak-event-card__badge" lang="he" dir="rtl">לא מאומת</span>
      </header>

      <span className="weak-event-card__title">
        {weakEvent.location_text ?? 'Location not named'}
      </span>

      <p className="weak-event-card__claim">
        {weakEvent.reports[0]?.claim ?? 'A report with no summary.'}
      </p>

      <section className="weak-event-card__sources">
        <h4>Reported by</h4>
        <ul>
          {weakEvent.reports.map((report, index) => (
            <li key={`${report.source_id}-${index}`}>
              {report.source_id} <span>({sourceLabel(report.tier)})</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="weak-event-card__confirm">
        <h4>Would confirm it</h4>
        <ul>
          {weakEvent.would_confirm.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </section>

      <footer className="weak-event-card__footer">
        <span className="weak-event-card__expiry">
          {remaining(weakEvent.expires_in_seconds)}
        </span>
        <div className="weak-event-card__actions">
          <button
            type="button"
            onClick={() => void decide('confirm')}
            disabled={busy !== null || !operator}
            title={operator ? undefined : 'Set an operator name before deciding'}
          >
            {busy === 'confirm' ? '…' : 'Mark confirmed'}
          </button>
          <button
            type="button"
            className="weak-event-card__dismiss"
            onClick={() => void decide('dismiss')}
            disabled={busy !== null || !operator}
            title={operator ? undefined : 'Set an operator name before deciding'}
          >
            {busy === 'dismiss' ? '…' : 'Dismiss'}
          </button>
        </div>
      </footer>

      {error && <p className="weak-event-card__error" role="alert">{error}</p>}
    </article>
  )
}

export default WeakEventCard
