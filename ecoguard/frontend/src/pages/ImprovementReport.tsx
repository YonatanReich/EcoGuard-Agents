/**
 * Improvement report page — the improvement agent's latest report, in full.
 *
 * Built to be printed: "Save as PDF" is the browser's own print-to-PDF, with a
 * print stylesheet that drops the controls and turns the page light. The
 * browser lays out Hebrew and right-to-left text correctly, which a PDF
 * library on the server would need bundled fonts and a shaping engine for —
 * operators' comments and settlement names are often in Hebrew.
 *
 * The counts at the top are computed by the backend from the feedback rows;
 * everything below them is the agent's writing.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import './visuals/improvementreport.css'

type Finding = { title: string; detail: string; feedback_ids: number[]; code_refs: string[] }
type Suggestion = { title: string; rationale: string; priority: 'high' | 'medium' | 'low'; code_refs: string[] }
type FollowUp = { earlier_suggestion: string; status: string; detail: string }

type ImprovementReportRow = {
  id: number
  created_at: string
  window_start: string | null
  window_end: string
  feedback_count: number
  model: string
  report: {
    stats: {
      handled: number
      surveys_answered: number
      verdicts: Partial<Record<'real' | 'false_report' | 'duplicate', number>>
      by_hazard: Record<string, number>
      average_plan_rating: number | null
      average_details_rating: number | null
    }
    summary: string
    problems: Finding[]
    strengths: Finding[]
    trends: string[]
    suggestions: Suggestion[]
    follow_up: FollowUp[]
  }
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; report: ImprovementReportRow | null }

function useLatestReport(): LoadState {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  useEffect(() => {
    let active = true
    fetch('/api/improvement/reports/latest')
      .then((response) => {
        if (!response.ok) throw new Error('Report unavailable')
        return response.json() as Promise<{ report: ImprovementReportRow | null }>
      })
      .then((data) => { if (active) setState({ status: 'ready', report: data.report }) })
      .catch(() => { if (active) setState({ status: 'error' }) })
    return () => { active = false }
  }, [])
  return state
}

function formatDate(timestamp: string) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Jerusalem',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(timestamp))
}

const VERDICT_LABELS = { real: 'Real', false_report: 'False reports', duplicate: 'Duplicates' } as const

function Refs({ feedbackIds = [], codeRefs }: { feedbackIds?: number[]; codeRefs: string[] }) {
  if (feedbackIds.length === 0 && codeRefs.length === 0) return null
  return (
    <p className="report__refs">
      {feedbackIds.length > 0 && <span>Feedback {feedbackIds.map((id) => `#${id}`).join(', ')}</span>}
      {codeRefs.map((ref) => <code key={ref}>{ref}</code>)}
    </p>
  )
}

function Findings({ title, findings }: { title: string; findings: Finding[] }) {
  if (findings.length === 0) return null
  return (
    <section className="report__section">
      <h2>{title}</h2>
      {findings.map((finding) => (
        <article key={finding.title} className="report__item">
          <h3 dir="auto">{finding.title}</h3>
          <p dir="auto">{finding.detail}</p>
          <Refs feedbackIds={finding.feedback_ids} codeRefs={finding.code_refs} />
        </article>
      ))}
    </section>
  )
}

function ImprovementReport() {
  const navigate = useNavigate()
  const state = useLatestReport()

  if (state.status !== 'ready' || !state.report) {
    return (
      <main className="report">
        <p className="report__empty">
          {state.status === 'loading' ? 'Loading…'
            : state.status === 'error' ? 'The report could not be loaded.'
            : 'No report has been written yet.'}
        </p>
        <button type="button" className="report__button" onClick={() => navigate('/system')}>
          Back to system
        </button>
      </main>
    )
  }

  const { report: row } = state
  const { stats, ...report } = row.report
  const verdicts = Object.entries(stats.verdicts) as Array<[keyof typeof VERDICT_LABELS, number]>

  return (
    <main className="report">
      <div className="report__controls">
        <button type="button" className="report__button" onClick={() => navigate('/system')}>
          Back to system
        </button>
        <button type="button" className="report__button report__button--primary" onClick={() => window.print()}>
          Save as PDF
        </button>
      </div>

      <header className="report__header">
        <p className="report__eyebrow">EcoGuard · Improvement report</p>
        <h1>{formatDate(row.created_at)}</h1>
        <p className="report__meta">
          Covers {row.window_start ? `${formatDate(row.window_start)} to ` : 'everything up to '}
          {formatDate(row.window_end)} · written by {row.model}
        </p>
      </header>

      <dl className="report__stats">
        <div><dt>Events handled</dt><dd>{stats.handled}</dd></div>
        <div><dt>Surveys answered</dt><dd>{stats.surveys_answered}</dd></div>
        {verdicts.map(([verdict, count]) => (
          <div key={verdict}><dt>{VERDICT_LABELS[verdict]}</dt><dd>{count}</dd></div>
        ))}
        <div><dt>Plan accuracy</dt><dd>{stats.average_plan_rating ?? '–'}<small> / 5</small></dd></div>
        <div><dt>Details accuracy</dt><dd>{stats.average_details_rating ?? '–'}<small> / 5</small></dd></div>
      </dl>
      <p className="report__hazards">
        {Object.entries(stats.by_hazard).map(([hazard, count]) => `${hazard.replaceAll('_', ' ')}: ${count}`).join(' · ')}
      </p>

      <section className="report__section">
        <h2>Summary</h2>
        <p dir="auto">{report.summary}</p>
      </section>

      <Findings title="What is wrong" findings={report.problems} />
      <Findings title="Where it is strong" findings={report.strengths} />

      {report.trends.length > 0 && (
        <section className="report__section">
          <h2>Trends</h2>
          <ul>{report.trends.map((trend) => <li key={trend} dir="auto">{trend}</li>)}</ul>
        </section>
      )}

      {report.suggestions.length > 0 && (
        <section className="report__section">
          <h2>Suggestions</h2>
          {report.suggestions.map((suggestion) => (
            <article key={suggestion.title} className="report__item">
              <h3 dir="auto">
                <span className={`report__priority report__priority--${suggestion.priority}`}>{suggestion.priority}</span>
                {suggestion.title}
              </h3>
              <p dir="auto">{suggestion.rationale}</p>
              <Refs codeRefs={suggestion.code_refs} />
            </article>
          ))}
        </section>
      )}

      {report.follow_up.length > 0 && (
        <section className="report__section">
          <h2>Earlier suggestions</h2>
          {report.follow_up.map((item) => (
            <article key={item.earlier_suggestion} className="report__item">
              <h3 dir="auto">
                <span className="report__status">{item.status.replaceAll('_', ' ')}</span>
                {item.earlier_suggestion}
              </h3>
              <p dir="auto">{item.detail}</p>
            </article>
          ))}
        </section>
      )}
    </main>
  )
}

/** The newest report's summary, for the improvement agent's System panel. */
export function LatestReportSummary() {
  const navigate = useNavigate()
  const state = useLatestReport()

  return (
    <section className="actor-panel__report">
      <h3>Latest report</h3>
      {state.status === 'loading' ? (
        <p>Loading…</p>
      ) : state.status === 'error' ? (
        <p>The report could not be loaded.</p>
      ) : !state.report ? (
        <p>No report yet. The first one is written the day after operators start marking events handled.</p>
      ) : (
        <>
          <p dir="auto">{state.report.report.summary}</p>
          <p className="actor-panel__report-meta">
            {formatDate(state.report.created_at)} · {state.report.feedback_count} handled event(s)
          </p>
          <button type="button" className="event-tool" onClick={() => navigate('/system/improvement-report')}>
            Open report
          </button>
        </>
      )}
    </section>
  )
}

export default ImprovementReport
