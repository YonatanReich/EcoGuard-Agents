/**
 * General feedback: anything an operator wants the developers to know about the
 * system, not tied to one event. It goes into the same table as the handled
 * survey and into the next improvement report.
 */

import { useEffect, useRef, useState, type FormEvent } from 'react'

/** Matches the API's limit, so the counter tells the truth. */
const MAX_LENGTH = 4000

function FeedbackDialog({ submittedBy, onClose }: {
  submittedBy: string
  onClose: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    dialogRef.current?.showModal()
  }, [])

  const [text, setText] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = (formEvent: FormEvent) => {
    formEvent.preventDefault()
    setIsSubmitting(true)
    setError(null)
    void fetch('/api/improvement/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, submitted_by: submittedBy.trim() || 'operator' }),
    })
      .then((response) => {
        if (!response.ok) throw new Error('Feedback was not recorded')
        onClose()
      })
      .catch(() => setError('Your feedback was not recorded. Try again.'))
      .finally(() => setIsSubmitting(false))
  }

  return (
    <dialog
      ref={dialogRef}
      className="survey"
      aria-labelledby="feedback-title"
      onCancel={(cancelEvent) => {
        cancelEvent.preventDefault()
        if (!isSubmitting) onClose()
      }}
    >
      <form onSubmit={send}>
        <header className="survey__header">
          <span className="survey__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              <path d="M8 9h8" />
              <path d="M8 13h5" />
            </svg>
          </span>
          <h2 id="feedback-title">Send feedback</h2>
          <p>What is working, what is not, and what you wish the system did. It goes straight to the developers' next report.</p>
        </header>

        <textarea
          aria-label="Feedback"
          value={text}
          onChange={(change) => setText(change.target.value)}
          placeholder="For example: the flood cards never say which roads are already closed."
          rows={6}
          maxLength={MAX_LENGTH}
          autoFocus
        />
        <span className="survey__count" aria-live="polite">{text.length} / {MAX_LENGTH}</span>

        {error && <p className="survey__error" role="alert">{error}</p>}

        <footer className="survey__actions">
          <button type="button" className="survey__button survey__button--quiet"
            onClick={onClose} disabled={isSubmitting}>
            Cancel
          </button>
          <button type="submit" className="survey__button survey__button--primary"
            disabled={isSubmitting || !text.trim()}>
            {isSubmitting ? 'Sending…' : 'Send'}
          </button>
        </footer>
      </form>
    </dialog>
  )
}

export default FeedbackDialog
