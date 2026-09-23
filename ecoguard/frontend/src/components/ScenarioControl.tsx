/**
 * Run a controlled scenario against the live pipeline, from the dashboard.
 *
 * Not a separate screen and not a replay. Pressing the button repoints the
 * detectors at a schema of authored observations and wakes them immediately;
 * everything after that — detection, coordination, analysis, planning,
 * allocation, projection — is the same code running against the same map. The
 * events that appear are produced now, not recorded earlier.
 *
 * The banner is deliberately loud. While a scenario is running the dashboard
 * is not showing the country, and an operator who forgot that would draw the
 * wrong conclusion from an empty map.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type ScenarioStatus = {
  running: boolean
  scenario: string | null
  schema: string | null
  started_at: string | null
  wave_running?: boolean
  stopping?: boolean
  counts?: Record<string, number>
}

const SCENARIO = 'demo_a'
const LABEL = 'Demo A'

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

  const send = async (path: string) => {
    setBusy(true)
    setError(null)
    try {
      const response = await fetch(path, { method: 'POST' })
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null
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
  // A stop requested during a wave is honoured only once that wave finishes,
  // so the search path is never switched out from under work in flight.
  const stopping = status?.stopping ?? false
  const incidents = status?.counts?.incidents ?? 0
  const projected = status?.counts?.event_projections ?? 0

  return (
    <div className="scenario">
      <button
        type="button"
        className={`scenario__button${running ? ' scenario__button--stop' : ''}`}
        disabled={busy || stopping}
        onClick={() =>
          void send(running ? '/api/scenario/stop' : `/api/scenario/start/${SCENARIO}`)
        }
        title={
          running
            ? 'Return the detectors to the live observations table'
            : 'Point the detectors at an authored scenario and wake them now'
        }
      >
        {busy ? '…' : stopping ? 'Ending…' : running ? `End ${LABEL}` : `Run ${LABEL}`}
      </button>

      {running && (
        <span className="scenario__banner" role="status">
          <span className="scenario__dot" aria-hidden="true" />
          {LABEL} — showing authored evidence, not live data
          <span className="scenario__counts">
            {incidents} incident{incidents === 1 ? '' : 's'} · {projected} projected
            {stopping
              ? ' · ending after this wave'
              : status?.wave_running
                ? ' · detecting…'
                : ''}
          </span>
        </span>
      )}

      {error && <span className="scenario__error">{error}</span>}
    </div>
  )
}

export default ScenarioControl
