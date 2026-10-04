/**
 * Demo scenarios — how the controlled runs were built, and how to start one.
 *
 * A demo here is not a recording and not a mock-up. The events were decided
 * first, then written backwards into the readings each real collector would
 * have produced for them, and the ordinary pipeline is pointed at those. This
 * page says that before it offers to run anything, because a score means
 * nothing to someone who has not been told what was asked.
 *
 * Starting a scenario hands over to the dashboard, which is where the events
 * appear as the pipeline produces them.
 */

import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'

type AuthoredEvent = {
  id: string
  event: string
  hazard: string
  latitude: number | null
  longitude: number | null
  expect_route: string | null
  expect_detected: boolean | null
  notes: string | null
}

type Scenario = {
  id: string
  label: string
  blurb: string
  event_count: number
  events: AuthoredEvent[]
}

const HAZARD_LABEL: Record<string, string> = {
  fire: 'Fire',
  flood: 'Flood',
  earthquake: 'Earthquake',
  air_pollution: 'Air pollution',
  fire_weather: 'Fire weather',
}

/** How each hazard's chip is tinted, matching the map's own palette. */
const HAZARD_TINT: Record<string, string> = {
  fire: '#f2622e',
  flood: '#2e8ae6',
  earthquake: '#a678d8',
  air_pollution: '#3fb89a',
  fire_weather: '#e0a13a',
}

/** The hazard colour as a CSS variable, so one palette drives chip, dot and bar. */
function tint(hazard: string): CSSProperties {
  return { '--tint': HAZARD_TINT[hazard] ?? '#9fb3d1' } as CSSProperties
}

/** Which hazards a scenario covers, in first-appearance order, without repeats. */
function hazardsOf(scenario: Scenario): string[] {
  return [...new Set(scenario.events.map((item) => item.hazard))]
}

function DemoScenarios() {
  const navigate = useNavigate()
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null)
  const [open, setOpen] = useState<Scenario | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [alreadyRunning, setAlreadyRunning] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    fetch('/api/scenario/catalog')
      .then(async (response) => {
        // A 404 here means the backend is running code from before this
        // endpoint existed. Checked explicitly because fetch does not reject
        // on an error status: the JSON parsed fine, the scenario list came
        // back undefined, and the section rendered empty with nothing to
        // explain itself — a broken page rather than a stale server.
        if (response.status === 404) {
          throw new Error(
            'This backend does not serve /api/scenario/catalog yet. Restart it to pick up the demo scenarios page.',
          )
        }
        if (!response.ok) {
          throw new Error(`The scenario catalogue returned ${response.status}.`)
        }
        const body = (await response.json()) as { scenarios?: Scenario[] }
        if (!Array.isArray(body.scenarios)) {
          throw new Error('The scenario catalogue came back in an unexpected shape.')
        }
        return body.scenarios
      })
      .then((list) => {
        if (live) setScenarios(list)
      })
      .catch((caught: unknown) => {
        if (!live) return
        setScenarios([])
        setError(caught instanceof Error ? caught.message : String(caught))
      })
    // A scenario left running from an earlier visit must not be startable
    // again: the second start would be refused and read as a broken button.
    fetch('/api/scenario/status')
      .then((response) => response.json())
      .then((status: { running?: boolean; scenario?: string | null }) => {
        if (live && status.running) setAlreadyRunning(status.scenario ?? 'a scenario')
      })
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [])

  const start = useCallback(
    async (scenario: Scenario) => {
      setBusy(true)
      setError(null)
      try {
        const response = await fetch(`/api/scenario/start/${scenario.id}`, {
          method: 'POST',
        })
        if (!response.ok) {
          const body = (await response.json().catch(() => null)) as
            | { detail?: string }
            | null
          throw new Error(body?.detail ?? 'The scenario controller refused')
        }
        navigate('/dashboard')
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught))
        setBusy(false)
      }
    },
    [navigate],
  )

  return (
    <main className="demos">
      <header className="demos__head">
        <button
          type="button"
          className="demos__back"
          onClick={() => navigate('/')}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
            <path
              d="M15 6l-6 6 6 6"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Back
        </button>
        <h1 className="demos__title">Demo scenarios</h1>
        <p className="demos__lede">
          Proving the system works is harder than showing it running. A live map
          with nothing on it could mean the country is quiet or that the
          detectors are broken, and there is no way to tell the two apart by
          looking. So we built events we already know the answer to.
        </p>
      </header>

      <section className="demos__method" aria-labelledby="method-heading">
        <h2 id="method-heading" className="demos__section-title">
          How the evidence was built
        </h2>
        <ol className="demos__steps">
          <li className="demos__step">
            <div className="demos__step-number">1</div>
            <div>
              <h3>We read what each provider actually sends</h3>
              <p>
                Every source has its own shape — NASA&nbsp;FIRMS publishes a
                satellite hotspot with a confidence band and a radiative power
                in megawatts; the Water Authority publishes a discharge reading
                against six official return-period thresholds. For an ephemeral
                stream, two consecutive readings at or above 1&nbsp;m³/s confirm a
                flood; for a perennial (flowing-baseline) stream, two consecutive
                readings at or above that station&rsquo;s Q2 confirm it. The higher
                return-period thresholds describe severity, not detection. The
                Ministry publishes a pollutant reading every five minutes on Israel
                standard time. We studied the schema of each one.
              </p>
            </div>
          </li>
          <li className="demos__step">
            <div className="demos__step-number">2</div>
            <div>
              <h3>We decided the events first</h3>
              <p>
                A large fire in central Eilat. A flash flood in Nahal Ashalim
                crossing the ten-year threshold. A dust episode at a Negev
                monitoring station. Written as an operator would describe them,
                before any data existed.
              </p>
            </div>
          </li>
          <li className="demos__step">
            <div className="demos__step-number">3</div>
            <div>
              <h3>Then we worked backwards to the raw readings</h3>
              <p>
                What would a satellite have seen, had that Eilat fire been
                burning? We wrote those rows — the hotspots, their confidence,
                their radiative power, the timestamps in the provider&rsquo;s own
                clock — into an observations table, alongside the Telegram
                messages and news items people would have posted about it.
                <strong> The system is handed readings, never
                conclusions.</strong>
              </p>
            </div>
          </li>
          <li className="demos__step">
            <div className="demos__step-number">4</div>
            <div>
              <h3>The real pipeline runs over it, unchanged</h3>
              <p>
                The same detectors, the same coordinator, the same analysers and
                planners, reading from an isolated copy of the tables while live
                collection carries on untouched. Nothing is told that a demo is
                happening. If the system finds the fire, it found it the way it
                would find a real one.
              </p>
            </div>
          </li>
        </ol>
        <p className="demos__aside">
          That direction is the whole point. Had we written the events and shown
          you the events, we would have proved nothing at all.
        </p>
      </section>

      <section className="demos__pick" aria-labelledby="pick-heading">
        <h2 id="pick-heading" className="demos__section-title">
          Choose a scenario
        </h2>

        {alreadyRunning && (
          <p className="demos__warning" role="status">
            A scenario is already running. End it from the dashboard before
            starting another.
          </p>
        )}
        {error && (
          <p className="demos__warning" role="alert">
            {error}
          </p>
        )}

        <div className="demos__cards">
          {(scenarios ?? []).map((scenario) => (
            <article key={scenario.id} className="demos__card">
              <h3 className="demos__card-title">{scenario.label}</h3>
              <p className="demos__card-blurb">{scenario.blurb}</p>
              <div className="demos__card-hazards">
                {hazardsOf(scenario).map((hazard) => (
                  <span key={hazard} className="demos__chip" style={tint(hazard)}>
                    {HAZARD_LABEL[hazard] ?? hazard}
                  </span>
                ))}
              </div>
              <div className="demos__card-meta">
                {scenario.event_count} event{scenario.event_count === 1 ? '' : 's'}
              </div>
              <button
                type="button"
                className="demos__card-button"
                onClick={() => setOpen(scenario)}
              >
                See what it contains
              </button>
            </article>
          ))}
          {scenarios === null && !error && (
            <p className="demos__card-blurb">Reading the catalogue…</p>
          )}
        </div>
      </section>

      {open && (
        <ScenarioModal
          scenario={open}
          busy={busy}
          blocked={Boolean(alreadyRunning)}
          onClose={() => setOpen(null)}
          onStart={() => void start(open)}
        />
      )}
    </main>
  )
}

/** Everything the run is about to be asked to find, before it is asked. */
function ScenarioModal({
  scenario,
  busy,
  blocked,
  onClose,
  onStart,
}: {
  scenario: Scenario
  busy: boolean
  blocked: boolean
  onClose: () => void
  onStart: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="demo-modal" role="dialog" aria-modal="true" aria-label={`${scenario.label} contents`}>
      <div className="demo-modal__backdrop" onClick={onClose} />
      <div className="demo-modal__panel">
        <header className="demo-modal__head">
          <div>
            <h2 className="demo-modal__title">{scenario.label}</h2>
            <p className="demo-modal__blurb">{scenario.blurb}</p>
          </div>
          <button
            type="button"
            className="demo-modal__close"
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

        <p className="demo-modal__intro">
          What this run should surface. None of it is handed to the system
          directly — each one has to be found in the readings.
        </p>

        <ol className="demo-modal__events">
          {scenario.events.map((item) => (
            <li key={item.id} className="demo-modal__event" style={tint(item.hazard)}>
              <div className="demo-modal__event-head">
                <span className="demo-modal__event-id">{item.id}</span>
                <span className="demo-modal__hazard">
                  {HAZARD_LABEL[item.hazard] ?? item.hazard}
                </span>
                {item.expect_route === 'uncorroborated' && (
                  <span className="demo-modal__tag">should stay unverified</span>
                )}
                {item.expect_detected === false && (
                  <span className="demo-modal__tag demo-modal__tag--quiet">
                    should be ignored
                  </span>
                )}
              </div>
              <p className="demo-modal__event-text">{item.event}</p>
              {item.notes && (
                <p className="demo-modal__event-notes">{item.notes}</p>
              )}
            </li>
          ))}
        </ol>

        <footer className="demo-modal__foot">
          <p className="demo-modal__foot-note">
            Starting takes you to the dashboard, where the events appear as the
            pipeline produces them. End the run there to see the score.
          </p>
          <div className="demo-modal__actions">
            <button type="button" className="demo-modal__cancel" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="demo-modal__start"
              onClick={onStart}
              disabled={busy || blocked}
            >
              {busy ? 'Starting…' : `Run ${scenario.label}`}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}

export default DemoScenarios
