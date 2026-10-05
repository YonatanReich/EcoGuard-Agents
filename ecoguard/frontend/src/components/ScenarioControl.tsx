/**
 * The banner and End control for a scenario already running.
 *
 * Starting one lives on the Demo scenarios page, not here. A run begins with
 * an explanation of how its evidence was built and a list of what it contains,
 * because a score means nothing to someone who was not told what was asked —
 * and a start button on the operator's own map invited pressing it without any
 * of that.
 *
 * What stays here is what an operator needs while a run is live: a loud banner
 * saying the map is not the country, the grade once detection has finished,
 * and the control that gives the live map back.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ScenarioScore from './ScenarioScore'
import type { ScenarioReport } from './ScenarioScore'

export type ScenarioStatus = {
  running: boolean
  scenario: string | null
  schema: string | null
  started_at: string | null
  wave_running?: boolean
  stopping?: boolean
  counts?: Record<string, number>
}

/** While a scenario runs the map changes as each wave lands, so it is polled
 *  faster than a dashboard normally would be. Cheap: it reads process memory
 *  and a handful of counts. */
const POLL_MS = 4000

function ScenarioControl({
  onStateChange,
}: {
  /** Called whenever the scenario starts, stops, or produces new rows, so the
   *  dashboard can refetch the event feed. */
  onStateChange: (status: ScenarioStatus) => void
}) {
  const [status, setStatus] = useState<ScenarioStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<ScenarioReport | null>(null)
  const [showReport, setShowReport] = useState(false)
  const navigate = useNavigate()
  // Compared rather than assumed: refetching the map on every poll would fight
  // the user's panning for no reason.
  const signature = useRef<string>('')

  const publish = useCallback(
    (next: ScenarioStatus) => {
      setStatus(next)
      const fingerprint = `${next.running}:${JSON.stringify(next.counts ?? {})}`
      if (fingerprint !== signature.current) {
        signature.current = fingerprint
        onStateChange(next)
      }
    },
    [onStateChange],
  )

  const poll = useCallback(async () => {
    try {
      const response = await fetch('/api/scenario/status')
      if (!response.ok) return
      publish((await response.json()) as ScenarioStatus)
    } catch {
      // A failed poll is not worth a banner; the next one is four seconds away.
    }
  }, [publish])

  useEffect(() => {
    void poll()
    const timer = window.setInterval(() => void poll(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [poll])

  /** End the run and wait until the live tables are back. A stop asked for
   *  during a wave is queued by the backend until that wave finishes. */
  const stopAndWait = useCallback(async () => {
    const response = await fetch('/api/scenario/stop', { method: 'POST' })
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null
      throw new Error(body?.detail ?? 'The scenario controller refused')
    }
    for (;;) {
      const current = (await (await fetch('/api/scenario/status')).json()) as ScenarioStatus
      publish(current)
      if (!current.running) return
      await new Promise((resolve) => window.setTimeout(resolve, 2000))
    }
  }, [publish])

  // A scenario is one forced detection wave. When it has finished, grade it -
  // but leave it running, so the cards stay on the map for questions. The demo
  // ends only when someone returns to the scenarios (or reruns it).
  const graded = useRef<string | null>(null)
  useEffect(() => {
    if (!status?.running || status.wave_running || status.stopping || !status.scenario) return
    const key = `${status.scenario}:${status.started_at}`
    if (graded.current === key) return
    graded.current = key
    fetch(`/api/scenario/report/${status.scenario}`)
      .then(async (response) => {
        if (!response.ok) throw new Error('The grader could not score this run.')
        setReport((await response.json()) as ScenarioReport)
        setShowReport(true)
      })
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : String(caught)),
      )
  }, [status])

  const backToScenarios = async () => {
    setBusy(true)
    setError(null)
    try {
      await stopAndWait()
      setReport(null)
      navigate('/demos')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  const rerun = async (scenario: string) => {
    setBusy(true)
    setError(null)
    setShowReport(false)
    setReport(null)
    try {
      await stopAndWait()
      const response = await fetch(`/api/scenario/start/${scenario}`, { method: 'POST' })
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null
        throw new Error(body?.detail ?? 'The scenario controller refused')
      }
      await poll()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  const running = status?.running ?? false
  const stopping = status?.stopping ?? false
  const incidents = status?.counts?.incidents ?? 0
  const projected = status?.counts?.event_projections ?? 0
  const runningLabel = report?.label
    ?? (status?.scenario
      ? status.scenario.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
      : 'Demo')

  if (!running && !error) return null

  return (
    <div className="scenario">
      {running && (
        <>
          <button
            type="button"
            className="scenario__button scenario__button--stop"
            disabled={busy || stopping}
            onClick={() => void backToScenarios()}
            title="End the demo, resume live collection and go back to the scenarios"
          >
            {busy || stopping ? 'Ending…' : 'Return to all scenarios'}
          </button>

          {report && !showReport && (
            <button type="button" className="scenario__button" onClick={() => setShowReport(true)}>
              Show grade
            </button>
          )}

          <span className="scenario__banner" role="status">
            <span className="scenario__dot" aria-hidden="true" />
            {runningLabel} — scenario data, not live
            <span className="scenario__counts">
              {incidents} incident{incidents === 1 ? '' : 's'} · {projected} projected
              {status?.wave_running ? ' · detecting…' : report ? ' · graded' : ' · grading…'}
            </span>
          </span>
        </>
      )}

      {error && <span className="scenario__error">{error}</span>}

      {report && showReport && (
        <ScenarioScore
          report={report}
          busy={busy}
          onClose={() => setShowReport(false)}
          onReturn={() => void backToScenarios()}
          onRerun={() => void rerun(report.scenario)}
        />
      )}
    </div>
  )
}

export default ScenarioControl
