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
 * saying the map is not the country, and the control that gives it back. Ending
 * a run fetches the grader's score and shows it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
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

  /**
   * End the run, then show what it found.
   *
   * The score is read after the stop returns, because a stop queued behind a
   * wave only completes when that wave does, and grading a half-finished run
   * would report a miss the system had not made.
   */
  const end = async () => {
    const scenario = status?.scenario
    setBusy(true)
    setError(null)
    try {
      const response = await fetch('/api/scenario/stop', { method: 'POST' })
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null
        throw new Error(body?.detail ?? 'The scenario controller refused')
      }
      await poll()
      if (scenario) {
        const graded = await fetch(`/api/scenario/report/${scenario}`)
        if (graded.ok) setReport((await graded.json()) as ScenarioReport)
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  const running = status?.running ?? false
  // A stop requested during a wave is honoured only once that wave finishes,
  // so the search path is never switched out from under work in flight.
  const stopping = status?.stopping ?? false
  const incidents = status?.counts?.incidents ?? 0
  const projected = status?.counts?.event_projections ?? 0
  const runningLabel = status?.scenario
    ? status.scenario.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    : 'Demo'

  if (!running && !report && !error) return null

  return (
    <div className="scenario">
      {running && (
        <>
          <button
            type="button"
            className="scenario__button scenario__button--stop"
            disabled={busy || stopping}
            onClick={() => void end()}
            title="Return the detectors to the live observations table and score the run"
          >
            {busy ? '…' : stopping ? 'Ending…' : `End ${runningLabel}`}
          </button>

          <span className="scenario__banner" role="status">
            <span className="scenario__dot" aria-hidden="true" />
            {runningLabel} — showing authored evidence, not live data
            <span className="scenario__counts">
              {incidents} incident{incidents === 1 ? '' : 's'} · {projected} projected
              {stopping
                ? ' · ending after this wave'
                : status?.wave_running
                  ? ' · detecting…'
                  : ''}
            </span>
          </span>
        </>
      )}

      {error && <span className="scenario__error">{error}</span>}

      {report && (
        <ScenarioScore report={report} onClose={() => setReport(null)} />
      )}
    </div>
  )
}

export default ScenarioControl
