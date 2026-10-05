/**
 * Demo scenarios — what each controlled run replays, how it is graded, and
 * the button that starts it.
 *
 * A demo here is not a recording and not a mock-up. The real pipeline is
 * pointed at the readings each provider sent (or, for the constructed tests,
 * would have sent), and what it produces is graded against what is known to
 * have happened. The page says that before it offers to run anything, because
 * a score means nothing to someone who has not been told what was asked.
 *
 * The words on each card come from the backend catalogue, next to the scenario
 * they describe, so the two cannot drift apart.
 */

import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
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

type Story = {
  label?: string
  kicker?: string
  blurb?: string
  incident?: string[]
  outcome?: string[]
  detection?: string[]
  value?: string[]
  passes?: string
}

type Scenario = {
  id: string
  label: string
  blurb: string
  story?: Story
  event_count: number
  events: AuthoredEvent[]
}

/** Replays of real events come first; the constructed tests after. */
const CONSTRUCTED = new Set(['demo_a', 'demo_b'])

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

const HOW_IT_WORKS = [
  {
    title: 'Replay',
    text: 'The real readings and news reports of the day are loaded, each only from the moment it would have reached us.',
  },
  {
    title: 'Run',
    text: 'The production system runs over them, unchanged, on a separate copy of the database.',
  },
  {
    title: 'Grade',
    text: 'When detection finishes, every card is checked against what really happened. The demo stays on the map until you return here.',
  },
]

const GRADING = [
  { verdict: 'pass', label: 'Passed', text: 'Detected, in the right place, and every required part of the plan is correct.' },
  { verdict: 'partial', label: 'Partly', text: 'Detected, but something is wrong or missing — each problem is listed.' },
  { verdict: 'miss', label: 'Missed', text: 'Never became an incident.' },
]

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
        // on an error status, and an empty page explains nothing.
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

  const list = scenarios ?? []
  const groups = [
    { title: 'Real events, replayed', items: list.filter((item) => !CONSTRUCTED.has(item.id)) },
    { title: 'Constructed tests', items: list.filter((item) => CONSTRUCTED.has(item.id)) },
  ]

  return (
    <main className="demos">
      <header className="demos__head">
        <button type="button" className="demos__back" onClick={() => navigate('/')}>
          <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
            <path d="M15 6l-6 6 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Back
        </button>
        <h1 className="demos__title">Demo scenarios</h1>
        <p className="demos__lede">
          Each demo replays a real emergency through the live system and grades
          what it produced against what actually happened. A map that only shows
          today cannot prove anything; a past event with a known answer can.
        </p>
      </header>

      <section className="demos__explain" aria-label="How demos work and how they are graded">
        <div className="demos__panel">
          <h2 className="demos__section-title">How a demo works</h2>
          <ol className="demos__flow">
            {HOW_IT_WORKS.map((step, index) => (
              <li key={step.title} className="demos__flow-step">
                <span className="demos__step-number">{index + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </li>
            ))}
          </ol>
        </div>
        <div className="demos__panel">
          <h2 className="demos__section-title">How it is graded</h2>
          <ul className="demos__grading">
            {GRADING.map((item) => (
              <li key={item.verdict}>
                <span className={`demos__verdict demos__verdict--${item.verdict}`}>{item.label}</span>
                <span>{item.text}</span>
              </li>
            ))}
          </ul>
          <p className="demos__grading-note">
            A demo passes only when every event passes and no incident appears
            that the scenario does not account for. Each card says what its
            events must get right.
          </p>
        </div>
      </section>

      <section className="demos__pick" aria-label="Scenarios">
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
        {scenarios === null && !error && <p className="demos__card-blurb">Reading the catalogue…</p>}

        {groups.map(
          (group) =>
            group.items.length > 0 && (
              <div key={group.title}>
                <h2 className="demos__section-title">{group.title}</h2>
                <div className="demos__cards">
                  {group.items.map((scenario) => (
                    <button
                      key={scenario.id}
                      type="button"
                      className="demos__card"
                      style={tint(hazardsOf(scenario)[0] ?? '')}
                      onClick={() => setOpen(scenario)}
                    >
                      {scenario.story?.kicker && (
                        <span className="demos__card-kicker">{scenario.story.kicker}</span>
                      )}
                      <span className="demos__card-title">{scenario.label}</span>
                      <span className="demos__card-blurb">{scenario.blurb}</span>
                      <span className="demos__card-foot">
                        <span className="demos__card-hazards">
                          {hazardsOf(scenario).map((hazard) => (
                            <span key={hazard} className="demos__chip" style={tint(hazard)}>
                              {HAZARD_LABEL[hazard] ?? hazard}
                            </span>
                          ))}
                        </span>
                        <span className="demos__card-meta">
                          {scenario.event_count} graded event{scenario.event_count === 1 ? '' : 's'}
                        </span>
                      </span>
                      <span className="demos__card-cta" aria-hidden="true">
                        Details
                        <svg viewBox="0 0 24 24" width="14" height="14">
                          <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ),
        )}
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

/** One titled block of the modal, skipped when the catalogue has nothing for it. */
function StorySection({ title, paragraphs, tone }: { title: string; paragraphs?: string[]; tone?: string }) {
  if (!paragraphs?.length) return null
  return (
    <section className={`demo-modal__section${tone ? ` demo-modal__section--${tone}` : ''}`}>
      <h3>{title}</h3>
      {paragraphs.map((text) => (
        <p key={text}>{text}</p>
      ))}
    </section>
  )
}

/** What the run replays, what it should find, and what it takes to pass.
 *  Rendered into <body>: the page's entrance animation leaves a transform on
 *  .demos, which would make a fixed overlay inside it scroll with the page. */
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
    // The page behind must not scroll under the open dialog.
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [onClose])

  const story = scenario.story ?? {}

  return createPortal(
    <div className="demo-modal" role="dialog" aria-modal="true" aria-label={scenario.label}>
      <div className="demo-modal__backdrop" onClick={onClose} />
      <div className="demo-modal__panel" style={tint(hazardsOf(scenario)[0] ?? '')}>
        <header className="demo-modal__head">
          <div>
            {story.kicker && <span className="demos__card-kicker">{story.kicker}</span>}
            <h2 className="demo-modal__title">{scenario.label}</h2>
            <p className="demo-modal__blurb">{scenario.blurb}</p>
          </div>
          <button type="button" className="demo-modal__close" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div className="demo-modal__story">
          <StorySection title="What happened" paragraphs={story.incident} />
          <StorySection title="The toll" paragraphs={story.outcome} tone="toll" />
          <div className="demo-modal__pair">
            <StorySection title="How EcoGuard catches it" paragraphs={story.detection} />
            <StorySection title="What it would have changed" paragraphs={story.value} />
          </div>
        </div>

        {story.passes && (
          <p className="demo-modal__passes">
            <strong>To pass:</strong> {story.passes}
          </p>
        )}

        <details className="demo-modal__graded">
          <summary>
            The {scenario.event_count} graded event{scenario.event_count === 1 ? '' : 's'}
          </summary>
          <ol className="demo-modal__events">
            {scenario.events.map((item) => (
              <li key={item.id} className="demo-modal__event" style={tint(item.hazard)}>
                <div className="demo-modal__event-head">
                  <span className="demo-modal__event-id">{item.id}</span>
                  <span className="demo-modal__hazard">{HAZARD_LABEL[item.hazard] ?? item.hazard}</span>
                  {item.expect_route === 'uncorroborated' && (
                    <span className="demo-modal__tag">should stay unverified</span>
                  )}
                  {item.expect_detected === false && (
                    <span className="demo-modal__tag demo-modal__tag--quiet">should be ignored</span>
                  )}
                </div>
                <p className="demo-modal__event-text">{item.event}</p>
              </li>
            ))}
          </ol>
        </details>

        <footer className="demo-modal__foot">
          <p className="demo-modal__foot-note">
            Starting opens the dashboard, where cards appear as the pipeline
            produces them. The demo ends and is graded on its own.
          </p>
          <div className="demo-modal__actions">
            <button type="button" className="demo-modal__cancel" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="demo-modal__start" onClick={onStart} disabled={busy || blocked}>
              {busy ? 'Starting…' : 'Run demo'}
            </button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  )
}

export default DemoScenarios
