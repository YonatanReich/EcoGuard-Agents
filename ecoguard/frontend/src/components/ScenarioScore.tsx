/**
 * The score for a finished scenario run, shown over the dashboard.
 *
 * Read from the grader rather than counted here, so the number on the screen
 * is the same one the command line reports. Every event the scenario was built
 * to contain is listed with what became of it, including the ones the system
 * was supposed to leave alone — a run that reports only its successes is not a
 * measurement.
 *
 * The run is still live behind it, so its cards can be opened and questioned;
 * leaving for the scenarios is what ends it. Rendered into <body> so no transformed
 * ancestor can pull the fixed overlay off the viewport.
 */

import { useEffect } from 'react'
import { createPortal } from 'react-dom'

export type ScenarioFinding = {
  id: string
  event: string
  expected_hazard: string | null
  expected_route: string | null
  verdict: string
  title: string | null
  incident_id: string | null
  marker_km_from_event: number | null
  problems: string[]
}

export type ScenarioReport = {
  scenario: string
  label?: string
  passes?: string
  events_expected: number
  events_passed: number
  events_partial: number
  events_missed: number
  incident_count: number
  spurious_incidents?: string[]
  findings: ScenarioFinding[]
}

const VERDICT_LABEL: Record<string, string> = {
  pass: 'Passed',
  partial: 'Partly',
  miss: 'Missed',
}

/** The ring's circumference, for r = 52. */
const RING = 2 * Math.PI * 52

function ScenarioScore({
  report,
  busy,
  onClose,
  onReturn,
  onRerun,
}: {
  report: ScenarioReport
  busy: boolean
  onClose: () => void
  onReturn: () => void
  onRerun: () => void
}) {

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const label = report.label ?? report.scenario
  const spurious = report.spurious_incidents?.length ?? 0
  const share = report.events_expected ? report.events_passed / report.events_expected : 0
  const outcome =
    share === 1 && spurious === 0 ? 'pass' : report.events_passed > 0 ? 'partial' : 'miss'
  const headline = { pass: 'Demo passed', partial: 'Partly passed', miss: 'Demo failed' }[outcome]

  return createPortal(
    <div className="score" role="dialog" aria-modal="true" aria-label={`${label} results`}>
      <div className="score__backdrop" onClick={onClose} />
      <div className={`score__panel score__panel--${outcome}`}>
        <header className="score__head">
          <div>
            <div className="score__eyebrow">Demo graded</div>
            <h2 className="score__title">{label}</h2>
          </div>
          <button type="button" className="score__close" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <section className="score__hero">
          <svg className="score__ring" viewBox="0 0 120 120" aria-hidden="true">
            <circle cx="60" cy="60" r="52" className="score__ring-track" />
            <circle
              cx="60"
              cy="60"
              r="52"
              className="score__ring-fill"
              strokeDasharray={RING}
              strokeDashoffset={RING * (1 - share)}
            />
          </svg>
          <div className="score__ring-label">
            <span className="score__big">{report.events_passed}</span>
            <span className="score__of">/ {report.events_expected}</span>
          </div>
          <div className="score__verdict-block">
            <p className={`score__outcome score__outcome--${outcome}`}>{headline}</p>
            <div className="score__tallies">
              <span className="score__tally score__tally--pass">{report.events_passed} passed</span>
              <span className="score__tally score__tally--partial">{report.events_partial} partly</span>
              <span className="score__tally score__tally--miss">{report.events_missed} missed</span>
              <span className="score__tally">{spurious} unexplained</span>
            </div>
            <p className="score__restored">
              <span className="score__restored-dot" aria-hidden="true" />
              The demo is still on the map. Close this to look at its cards;
              returning to the scenarios ends it and brings back live data.
            </p>
          </div>
        </section>

        {report.passes && (
          <p className="score__rule">
            <strong>To pass:</strong> {report.passes}
          </p>
        )}

        <ul className="score__events">
          {report.findings.map((finding) => (
            <li key={finding.id} className={`score__event score__event--${finding.verdict}`}>
              <div className="score__event-head">
                <span className="score__verdict">{VERDICT_LABEL[finding.verdict] ?? finding.verdict}</span>
                <span className="score__event-id">{finding.id}</span>
              </div>
              <p className="score__event-text">{finding.event}</p>
              {finding.title && (
                <p className="score__event-title">
                  Reported as &ldquo;{finding.title}&rdquo;
                  {finding.marker_km_from_event !== null &&
                    ` · ${finding.marker_km_from_event.toFixed(2)} km from the real location`}
                </p>
              )}
              {finding.problems.length > 0 && (
                <ul className="score__problems">
                  {finding.problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>

        <footer className="score__foot">
          <span className="score__foot-note">
            {report.incident_count} incident{report.incident_count === 1 ? '' : 's'} opened
            {spurious > 0 && ` · ${spurious} not accounted for by the scenario`}
          </span>
          <div className="score__actions">
            <button type="button" className="score__done" onClick={onReturn} disabled={busy}>
              Return to all scenarios
            </button>
            <button type="button" className="score__rerun" onClick={onRerun} disabled={busy}>
              {busy ? 'Working…' : 'Rerun demo'}
            </button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  )
}

export default ScenarioScore
