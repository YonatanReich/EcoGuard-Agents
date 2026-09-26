/**
 * The score for a finished scenario run, shown over the dashboard.
 *
 * Read from the grader rather than counted here, so the number on the screen
 * is the same one the command line reports. Every event the scenario was built
 * to contain is listed with what became of it, including the ones the system
 * was supposed to leave alone — a run that reports only its successes is not a
 * measurement.
 *
 * Dismissable, and dismissing it does not re-run anything.
 */

import { useEffect } from 'react'

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
  events_expected: number
  events_passed: number
  events_partial: number
  events_missed: number
  incident_count: number
  spurious_incidents?: string[]
  findings: ScenarioFinding[]
}

const VERDICT_CLASS: Record<string, string> = {
  pass: 'score__verdict--pass',
  partial: 'score__verdict--partial',
  miss: 'score__verdict--miss',
}

const VERDICT_LABEL: Record<string, string> = {
  pass: 'Found',
  partial: 'Partly',
  miss: 'Missed',
}

function ScenarioScore({
  report,
  onClose,
}: {
  report: ScenarioReport
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const label = report.scenario.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  const spurious = report.spurious_incidents?.length ?? 0

  return (
    <div className="score" role="dialog" aria-modal="true" aria-label={`${label} results`}>
      <div className="score__backdrop" onClick={onClose} />
      <div className="score__panel">
        <header className="score__head">
          <div>
            <div className="score__eyebrow">Run complete</div>
            <h2 className="score__title">{label}</h2>
          </div>
          <button
            type="button"
            className="score__close"
            onClick={onClose}
            aria-label="Close"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                d="M6 6l12 12M18 6L6 18"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </header>

        <div className="score__headline">
          <span className="score__big">{report.events_passed}</span>
          <span className="score__of">of {report.events_expected}</span>
          <span className="score__caption">authored events found in full</span>
        </div>

        <div className="score__tallies">
          <div className="score__tally">
            <span className="score__tally-value score__tally-value--pass">
              {report.events_passed}
            </span>
            <span className="score__tally-label">found</span>
          </div>
          <div className="score__tally">
            <span className="score__tally-value score__tally-value--partial">
              {report.events_partial}
            </span>
            <span className="score__tally-label">partly</span>
          </div>
          <div className="score__tally">
            <span className="score__tally-value score__tally-value--miss">
              {report.events_missed}
            </span>
            <span className="score__tally-label">missed</span>
          </div>
          <div className="score__tally">
            <span className="score__tally-value">{spurious}</span>
            <span className="score__tally-label">unexplained</span>
          </div>
        </div>

        <ul className="score__events">
          {report.findings.map((finding) => (
            <li key={finding.id} className="score__event">
              <span
                className={`score__verdict ${VERDICT_CLASS[finding.verdict] ?? ''}`}
              >
                {VERDICT_LABEL[finding.verdict] ?? finding.verdict}
              </span>
              <div className="score__event-body">
                <p className="score__event-text">
                  <span className="score__event-id">{finding.id}</span>
                  {finding.event}
                </p>
                {finding.title && (
                  <p className="score__event-title">
                    Reported as &ldquo;{finding.title}&rdquo;
                    {finding.marker_km_from_event !== null &&
                      `, ${finding.marker_km_from_event.toFixed(2)} km from where it was authored`}
                  </p>
                )}
                {finding.problems.map((problem) => (
                  <p key={problem} className="score__event-problem">
                    {problem}
                  </p>
                ))}
              </div>
            </li>
          ))}
        </ul>

        <footer className="score__foot">
          <span className="score__foot-note">
            {report.incident_count} incident
            {report.incident_count === 1 ? '' : 's'} opened in total
            {spurious > 0 &&
              ` · ${spurious} not accounted for by the scenario`}
          </span>
          <button type="button" className="score__done" onClick={onClose}>
            Close
          </button>
        </footer>
      </div>
    </div>
  )
}

export default ScenarioScore
