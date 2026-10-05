/**
 * The survey an operator answers when they mark an event handled.
 *
 * Both ways out of it close the incident: "Send feedback" records the answers,
 * "Close without feedback" records only that it was handled. Cancel (and
 * Escape) leave the incident open, because a stray key must not end a live
 * emergency.
 *
 * Each open question is paired with a 1-5 rating. The text says why; the
 * rating is what the improvement agent can count across a week.
 */

import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { SharedEvent } from '../types/events'

export type OperatorFeedback = {
  verdict: 'real' | 'false_report' | 'duplicate'
  plan_rating: number | null
  plan_comment: string | null
  details_rating: number | null
  details_comment: string | null
  missing_information: string | null
}

const VERDICTS: Array<[OperatorFeedback['verdict'], string, string]> = [
  ['real', 'Confirm event', 'It happened as reported.'],
  ['false_report', 'Mark as a fake report', 'Nothing happened there.'],
  ['duplicate', 'Duplicate', 'Already handled under another event.'],
]

const RATINGS = [1, 2, 3, 4, 5]

/** Empty text is no answer, not an empty answer. */
const answer = (text: string) => text.trim() || null

function Rating({ name, label, value, onChange }: {
  name: string
  label: string
  value: number | null
  onChange: (value: number) => void
}) {
  return (
    <fieldset className="survey__rating">
      <legend>{label}</legend>
      <div className="survey__scale">
        <span className="survey__scale-end">Not at all</span>
        {RATINGS.map((rating) => (
          <label key={rating} className="survey__point">
            <input
              type="radio"
              name={name}
              value={rating}
              checked={value === rating}
              onChange={() => onChange(rating)}
            />
            <span>{rating}</span>
          </label>
        ))}
        <span className="survey__scale-end">Fully</span>
      </div>
    </fieldset>
  )
}

function HandledSurvey({ event, isSubmitting, error, onSubmit, onCancel }: {
  event: SharedEvent
  isSubmitting: boolean
  /** Shown when the last submission failed; the incident is still open. */
  error: string | null
  onSubmit: (feedback: OperatorFeedback | null) => void
  onCancel: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    dialogRef.current?.showModal()
  }, [])

  const [verdict, setVerdict] = useState<OperatorFeedback['verdict'] | null>(null)
  const [planRating, setPlanRating] = useState<number | null>(null)
  const [planComment, setPlanComment] = useState('')
  const [detailsRating, setDetailsRating] = useState<number | null>(null)
  const [detailsComment, setDetailsComment] = useState('')
  const [missing, setMissing] = useState('')

  const send = (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (!verdict) return
    onSubmit({
      verdict,
      plan_rating: planRating,
      plan_comment: answer(planComment),
      details_rating: detailsRating,
      details_comment: answer(detailsComment),
      missing_information: answer(missing),
    })
  }

  return (
    <dialog
      ref={dialogRef}
      className="survey"
      aria-labelledby="survey-title"
      onCancel={(cancelEvent) => {
        cancelEvent.preventDefault()
        if (!isSubmitting) onCancel()
      }}
    >
      <form onSubmit={send}>
        <header className="survey__header">
          <span className="survey__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg>
          </span>
          <h2 id="survey-title">Event handled</h2>
          <p>{event.title}</p>
        </header>

        <fieldset className="survey__verdict">
          <legend>What was it?</legend>
          {VERDICTS.map(([value, label, hint]) => (
            <label key={value} className={`survey__choice${verdict === value ? ' survey__choice--on' : ''}`}>
              <input
                type="radio"
                name="verdict"
                value={value}
                checked={verdict === value}
                onChange={() => setVerdict(value)}
              />
              <span className="survey__choice-label">{label}</span>
              <span className="survey__choice-hint">{hint}</span>
            </label>
          ))}
        </fieldset>

        <section className="survey__question">
          <Rating name="plan" label="Was the suggested response plan accurate?"
            value={planRating} onChange={setPlanRating} />
          <textarea value={planComment} onChange={(change) => setPlanComment(change.target.value)}
            placeholder="What was right or wrong about it (optional)" rows={2} maxLength={4000} />
        </section>

        <section className="survey__question">
          <Rating name="details" label="Were the event details accurate?"
            value={detailsRating} onChange={setDetailsRating} />
          <textarea value={detailsComment} onChange={(change) => setDetailsComment(change.target.value)}
            placeholder="Location, severity, timing, sources (optional)" rows={2} maxLength={4000} />
        </section>

        <section className="survey__question">
          <label className="survey__label" htmlFor="survey-missing">
            Was there information missing from the report that would have helped you handle this event better?
          </label>
          <textarea id="survey-missing" value={missing} onChange={(change) => setMissing(change.target.value)}
            placeholder="Optional" rows={2} maxLength={4000} />
        </section>

        {error && <p className="survey__error" role="alert">{error}</p>}

        <footer className="survey__actions">
          <button type="button" className="survey__button survey__button--quiet"
            onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </button>
          <button type="button" className="survey__button"
            onClick={() => onSubmit(null)} disabled={isSubmitting}>
            Close without feedback
          </button>
          <button type="submit" className="survey__button survey__button--primary"
            disabled={isSubmitting || !verdict}
            title={verdict ? undefined : 'Choose what the event was first'}>
            {isSubmitting ? 'Sending…' : 'Send feedback'}
          </button>
        </footer>
      </form>
    </dialog>
  )
}

export default HandledSurvey
