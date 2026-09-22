/**
 * System page — every actor in the pipeline, and which ones are working now.
 *
 * One lane per pipeline stage, in the order data flows through them. A box
 * glows while its actor is actually running in the backend: each actor's entry
 * point is marked with @live_actor, and /api/system/actors reports which are
 * in flight. Polled every 1.5 s; because most runs last well under that, the
 * page also watches each actor's run counter and flashes a box whose actor ran
 * between two looks, so a sub-second detector pass is never invisible.
 *
 * Clicking a box opens its panel from below, the same dock as the dashboard's
 * event panel.
 */

import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import HazardIcon from '../components/HazardIcon'
import { ACTORS, STAGES, type Actor, type ActorIcon } from './systemActors'
import './visuals/dashboard.css'
import './visuals/system.css'

type ActorState = {
  live: boolean
  runs: number
  last_started_at: string | null
  last_finished_at: string | null
  last_outcome: 'ok' | 'error' | null
}

type SystemState = {
  actors: Record<string, ActorState>
  pipeline: { scheduler_running: boolean; next_wave_at: string | null }
  server_time: string
}

const POLL_MS = 1500
// How long a box stays lit after a run that started and ended between polls.
const FLASH_MS = 2500


// ===== Icons ================================================================

const PATHS: Partial<Record<ActorIcon, ReactNode>> = {
  satellite: <><path d="M13 7 9 3 5 7l4 4" /><path d="m17 11 4 4-4 4-4-4" /><path d="m8 12 4 4 6-6-4-4Z" /><path d="m16 8 3-3" /><path d="M9 21a6 6 0 0 0-6-6" /></>,
  thermometer: <path d="M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z" />,
  message: <><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><path d="M13 8H7" /><path d="M17 12H7" /></>,
  funnel: <path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" />,
  send: <><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></>,
  merge: <><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M6 21V9a9 9 0 0 0 9 9" /></>,
  droplet: <path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z" />,
  clipboard: <><rect x="8" y="2" width="8" height="4" rx="1" /><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><path d="M12 11h4" /><path d="M12 16h4" /><path d="M8 11h.01" /><path d="M8 16h.01" /></>,
  truck: <><path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2" /><path d="M15 18H9" /><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.62l-3.48-4.35A1 1 0 0 0 17.52 8H14" /><circle cx="17" cy="18" r="2" /><circle cx="7" cy="18" r="2" /></>,
}

function ActorGlyph({ icon }: { icon: ActorIcon }) {
  if (icon === 'fire' || icon === 'flood' || icon === 'earthquake' || icon === 'air_pollution') {
    return <HazardIcon kind={icon} />
  }
  return (
    <svg className="hazard-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[icon]}
    </svg>
  )
}


// ===== Time =================================================================

function spanText(seconds: number) {
  if (seconds < 60) return `${Math.round(seconds)} s`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  return `${(seconds / 3600).toFixed(1)} h`
}

/** "3 min ago", measured on the server clock so browser skew cannot show. */
function agoText(timestamp: string | null, serverTime: string | undefined) {
  if (!timestamp || !serverTime) return null
  return `${spanText(Math.max(0, (Date.parse(serverTime) - Date.parse(timestamp)) / 1000))} ago`
}

function untilText(timestamp: string | null, serverTime: string | undefined) {
  if (!timestamp || !serverTime) return null
  return spanText(Math.max(0, (Date.parse(timestamp) - Date.parse(serverTime)) / 1000))
}

function statusText(state: ActorState | undefined, live: boolean, serverTime: string | undefined) {
  if (live) return 'Running now'
  if (!state) return 'Not run since the server started'
  const ago = agoText(state.last_finished_at, serverTime)
  return `Last ran ${ago ?? 'recently'}${state.last_outcome === 'error' ? ' · failed' : ''}`
}


// ===== Page =================================================================

function System() {
  const navigate = useNavigate()
  const location = useLocation()
  const backTo = (location.state as { from?: string } | null)?.from ?? '/dashboard'

  const [system, setSystem] = useState<SystemState | null>(null)
  const [offline, setOffline] = useState(false)
  const [flashUntil, setFlashUntil] = useState<Record<string, number>>({})
  // The clock flashes are measured against, advanced by each poll.
  const [now, setNow] = useState(0)
  const seenRuns = useRef<Record<string, number>>({})

  // Poll the live registry. A run counter that moved since the last look
  // means the actor ran in between, even if it is idle again now.
  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const response = await fetch('/api/system/actors')
        if (!response.ok) throw new Error('System state unavailable')
        const next = await response.json() as SystemState
        if (!active) return
        const now = Date.now()
        const flashes: Record<string, number> = {}
        for (const [id, state] of Object.entries(next.actors)) {
          const previous = seenRuns.current[id]
          if (previous !== undefined && state.runs > previous) flashes[id] = now + FLASH_MS
          seenRuns.current[id] = state.runs
        }
        if (Object.keys(flashes).length > 0) setFlashUntil((current) => ({ ...current, ...flashes }))
        setNow(now)
        setSystem(next)
        setOffline(false)
      } catch {
        if (active) setOffline(true)
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), POLL_MS)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  const isLive = useCallback(
    (id: string) => Boolean(system?.actors[id]?.live) || (flashUntil[id] ?? 0) > now,
    [system, flashUntil, now],
  )

  // The panel: kept after closing so it can animate shut with its content.
  const [openActor, setOpenActor] = useState<Actor | null>(null)
  const [panelOpen, setPanelOpen] = useState(false)
  const open = (actor: Actor) => {
    setOpenActor(actor)
    setPanelOpen(true)
  }

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setPanelOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Arrow keys walk the boxes in pipeline order.
  const lanesRef = useRef<HTMLDivElement>(null)
  const onLanesKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    if (!step || !lanesRef.current) return
    const boxes = [...lanesRef.current.querySelectorAll<HTMLButtonElement>('.actor')]
    const index = boxes.indexOf(document.activeElement as HTMLButtonElement)
    const next = boxes[Math.min(boxes.length - 1, Math.max(0, (index < 0 ? 0 : index + step)))]
    if (next) {
      event.preventDefault()
      next.focus()
    }
  }

  const liveCount = ACTORS.filter((actor) => isLive(actor.id)).length
  const nextWave = untilText(system?.pipeline.next_wave_at ?? null, system?.server_time)

  return (
    <main className="system">
      <header className="dashboard__header system__header">
        <div className="dashboard__brand">
          <svg className="dashboard__leaf" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M5 27C5 13 13 5 28 4c-1 15-9 23-23 23z" />
            <path d="M5 27 19 13" className="dashboard__leaf-vein" />
          </svg>
          <h1 className="dashboard__title"><span className="dashboard__eco">Eco</span>Guard</h1>
          <span className="system__crumb">System</span>
        </div>

        <p className="system__pipeline">
          {offline ? (
            <span className="system__pill system__pill--down">Backend unreachable</span>
          ) : !system ? (
            <span className="system__pill">Connecting…</span>
          ) : system.pipeline.scheduler_running ? (
            <>
              <span className="system__pill system__pill--up">Pipeline running</span>
              {nextWave && <span>Next wave in {nextWave}</span>}
              <span>{liveCount} live now</span>
            </>
          ) : (
            <span className="system__pill system__pill--down">Scheduler stopped</span>
          )}
        </p>

        <button type="button" className="logout-button" onClick={() => navigate(backTo)}>
          Back to dashboard
        </button>
      </header>

      <div className="system__body">
        <div className="system__lanes" ref={lanesRef} onKeyDown={onLanesKey}>
          {STAGES.map((stage, index) => (
            <section key={stage.id} className="lane" aria-labelledby={`lane-${stage.id}`}>
              <header className="lane__head">
                <span className="lane__step">{index + 1}</span>
                <h2 id={`lane-${stage.id}`}>{stage.name}</h2>
                <p>{stage.summary}</p>
              </header>
              <div className="lane__grid">
                {ACTORS.filter((actor) => actor.stage === stage.id).map((actor) => {
                  const live = isLive(actor.id)
                  const state = system?.actors[actor.id]
                  return (
                    <button
                      key={actor.id}
                      type="button"
                      className={`actor${live ? ' actor--live' : ''}${openActor?.id === actor.id && panelOpen ? ' actor--open' : ''}`}
                      style={{ '--accent': actor.accent } as CSSProperties}
                      onClick={() => open(actor)}
                    >
                      <span className="actor__top">
                        <span className="actor__icon"><ActorGlyph icon={actor.icon} /></span>
                        <span className="actor__name">{actor.name}</span>
                        {live && <span className="actor__live">Live</span>}
                      </span>
                      <span className="actor__summary">{actor.summary}</span>
                      <span className={`actor__status${state?.last_outcome === 'error' && !live ? ' actor__status--error' : ''}`}>
                        {statusText(state, live, system?.server_time)}
                      </span>
                    </button>
                  )
                })}
              </div>
            </section>
          ))}
        </div>

        <div className={`event-dock${panelOpen ? ' event-dock--open' : ''}`} inert={!panelOpen}>
          <div className="event-dock__inner">
            {openActor && (
              <ActorPanel
                actor={openActor}
                state={system?.actors[openActor.id]}
                live={isLive(openActor.id)}
                serverTime={system?.server_time}
                onClose={() => setPanelOpen(false)}
              />
            )}
          </div>
        </div>
      </div>
    </main>
  )
}


function ActorPanel({ actor, state, live, serverTime, onClose }: {
  actor: Actor
  state: ActorState | undefined
  live: boolean
  serverTime: string | undefined
  onClose: () => void
}) {
  const stage = STAGES.find((candidate) => candidate.id === actor.stage)
  return (
    <section className="event-panel actor-panel" style={{ '--hazard': actor.accent, '--accent': actor.accent } as CSSProperties}
      aria-label={`${actor.name} details`}>
      <header className="event-panel__header">
        <span className="event-panel__glyph"><ActorGlyph icon={actor.icon} /></span>
        <h2 className="event-panel__title">{actor.name}</h2>
        <span className="event-panel__urgency event-panel__urgency--advisory">{stage?.name}</span>
        {live && <span className="actor__live">Live</span>}
        <button type="button" className="event-panel__close" onClick={onClose} aria-label="Close actor details">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
        </button>
      </header>

      <div className="actor-panel__body">
        <section>
          <h3>Role in the system</h3>
          <p>{actor.role}</p>
        </section>
        <section>
          <h3>How it works</h3>
          <ol>{actor.how.map((step) => <li key={step}>{step}</li>)}</ol>
        </section>
        <section>
          <h3>Based on</h3>
          <ul>{actor.basedOn.map((source) => <li key={source}>{source}</li>)}</ul>
        </section>
        <section>
          <h3>Right now</h3>
          <p className={`actor-panel__now${live ? ' actor-panel__now--live' : ''}`}>
            {statusText(state, live, serverTime)}
          </p>
          <dl className="actor-panel__facts">
            <div><dt>Runs since start</dt><dd>{state?.runs ?? 0}</dd></div>
            <div><dt>Schedule</dt><dd>{actor.runs}</dd></div>
            <div><dt>Live when</dt><dd><code>{actor.wiredTo}</code> is running</dd></div>
          </dl>
        </section>
      </div>
    </section>
  )
}

export default System
