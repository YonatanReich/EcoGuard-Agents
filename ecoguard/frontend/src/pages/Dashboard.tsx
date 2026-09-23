/**
 * Dashboard page — the main operator view at /dashboard.
 *
 * Responsible for orchestrating the live environmental map.
 *
 * The same component serves /demo with `demo` set. Only the event feed
 * changes: the demo screen reads fabricated incidents from a separate
 * database so the allocator, the response plans and the modals can be shown
 * working without waiting for something real to happen. Everything else —
 * stations, districts, the lake — stays live, because it is reference data
 * and faking it would only make the demo less honest.
 */

import {
  useCallback,
  useState,
  useEffect,
  useMemo,
} from 'react'

import { useNavigate } from 'react-router-dom'
import { MapProvider, useMap } from 'react-map-gl/mapbox'

import MapView from '../components/MapView'


import EventCard from '../components/EventCard'
import WeakEventCard from '../components/WeakEventCard'
import EventLegend from '../components/EventLegend'
import EventModal from '../components/EventModal'
import { classify } from '../components/hazards'
import FireRiskLayer from '../components/layers/FireRiskLayer'

import FloodLegend from '../components/FloodLegend'
import FireRiskAlert from '../components/FireRiskAlert'
import KinneretLevelCard from '../components/KinneretLevelCard'
import ScenarioControl from '../components/ScenarioControl'
import { clusterHighRiskCells, type FireRiskCluster } from '../components/fireRiskClusters'
import { normalizeNationalRiskScanResponse, type NationalRiskScan } from '../components/fireRiskScan'
import FireDistrictsLayer from '../components/layers/FireDistrictsLayer'
import MdaDistrictsLayer from '../components/layers/MdaDistrictsLayer'
import TownSearch from '../components/TownSearch'
import WhatToSeeControl from '../components/WhatToSeeControl'
import FireStationsLayer from '../components/layers/FireStationsLayer'
import PoliceStationsLayer from '../components/layers/PoliceStationsLayer'
import MdaStationsLayer from '../components/layers/MdaStationsLayer'
import AirPollutionCorridorLayer from '../components/layers/AirPollutionCorridorLayer'
import FireSpreadLayer from '../components/layers/FireSpreadLayer'
import ResourceAllocationLayer from '../components/layers/ResourceAllocationLayer'
import SettlementGlowLayer from '../components/layers/SettlementGlowLayer'
import type { WeakEvent, WeakEventFeed } from '../types/weakEvents'
import {
  type FireEvent,
  type EarthquakeEvent,
  type FloodEvent,
  type SharedEvent,
  type SharedEventFeed,
} from '../types/events'

import './visuals/dashboard.css'


/** The zoom each hazard is framed at when opened: an earthquake's impact
 *  area spans tens of kilometres, a fire's front a few hundred metres. */
const FLY_ZOOM: Record<SharedEvent['type'], number> = {
  fire: 13,
  flood: 12.5,
  earthquake: 9.5,
  air_pollution: 12,
  other: 12,
}

/** Flies the map to the event just opened. Rendered inside MapView so it can
 *  reach the map; `at` makes a second click on the same card fly again. */
function FlyToEvent({ request }: { request: { event: SharedEvent; at: number } | null }) {
  const { current: map } = useMap()
  useEffect(() => {
    if (!map || !request) return
    map.flyTo({
      center: [request.event.longitude, request.event.latitude],
      zoom: FLY_ZOOM[request.event.type],
      duration: 1600,
      essential: true,
    })
  }, [map, request])
  return null
}


function Dashboard({ demo = false }: { demo?: boolean }) {
  const [projectedEvents, setProjectedEvents] =
    useState<SharedEvent[]>([])
  // Held apart from `events` on purpose. A weak event is not a SharedEvent and
  // must never reach the code that assumes something is actually happening.
  const [weakEvents, setWeakEvents] = useState<WeakEvent[]>([])
  // Who is on shift. There is no auth in this application, and inventing one
  // to satisfy "recorded with the operator's id" would be a far larger change
  // than the requirement asks for. A name the operator types once, kept in
  // this browser, attributes the decision honestly — and the API stores
  // whatever it is told, so a real identity later replaces this and nothing
  // downstream changes.
  const [operatorName, setOperatorName] = useState<string>(() => {
    try {
      return window.localStorage.getItem('ecoguard.operator') ?? ''
    } catch {
      return ''
    }
  })
  const [airPollutionPreview, setAirPollutionPreview] =
    useState<SharedEvent | null>(null)
  const [floodPreviewEvents, setFloodPreviewEvents] =
    useState<SharedEvent[]>([])

  // One feed, one id scheme. The legacy /api/detected-events point query used
  // to be merged in here, and because its ids are hotspot hashes rather than
  // incident ids, a fire seen by both paths rendered as two cards — the legacy
  // one with no detection verdict, spread or exposure.
  const liveEvents = projectedEvents

  const events = useMemo(
    () => [
      ...floodPreviewEvents,
      ...(airPollutionPreview ? [airPollutionPreview] : []),
      ...liveEvents,
    ],
    [airPollutionPreview, floodPreviewEvents, liveEvents],
  )

  /** The event shown in the panel under the map, from a card or a marker.
   *  Kept after the panel closes so it can animate shut with content in it. */
  const [openEvent, setOpenEvent] =
    useState<SharedEvent | null>(null)
  const [panelOpen, setPanelOpen] = useState(false)
  const [flyRequest, setFlyRequest] =
    useState<{ event: SharedEvent; at: number } | null>(null)

  /** The open event's optimal routes, and its simulated vehicles on them.
   *  Both belong to the open event and reset whenever it changes or closes,
   *  so nothing is left drawn without its controls on screen. */
  const [routesShown, setRoutesShown] = useState(false)
  const [vehiclesShown, setVehiclesShown] = useState(false)
  const [directionsStationKey, setDirectionsStationKey] =
    useState<string | null>(null)

  /** The event selected on the map; closing its modal must not clear it. */
  const [selectedEventKey, setSelectedEventKey] =
    useState<string | null>(null)

  const selectedEvent = useMemo(
    () => events.find(
      (event) => `${event.type}:${event.id}` === selectedEventKey,
    ) ?? null,
    [events, selectedEventKey],
  )

  const selectAndOpenEvent = (event: SharedEvent) => {
    setSelectedEventKey(`${event.type}:${event.id}`)
    setDirectionsStationKey(null)
    setOpenEvent(event)
    setPanelOpen(true)
    setFlyRequest({ event, at: Date.now() })
    setRoutesShown(false)
    setVehiclesShown(false)
  }

  const showStationDirections = (event: SharedEvent, stationKey: string) => {
    setSelectedEventKey(`${event.type}:${event.id}`)
    setDirectionsStationKey(stationKey)
    setOpenEvent(event)
    setPanelOpen(true)
  }

  const closePanel = () => {
    setPanelOpen(false)
    setDirectionsStationKey(null)
    setRoutesShown(false)
    setVehiclesShown(false)
  }

  useEffect(() => {
    if (
      !import.meta.env.DEV ||
      new URLSearchParams(window.location.search).get('airPollutionPreview') !== '1'
    ) {
      return
    }

    let active = true
    void import('../dev/airPollutionPreview').then(({ airPollutionPreviewEvent }) => {
      if (active) setAirPollutionPreview(airPollutionPreviewEvent)
    })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (
      new URLSearchParams(window.location.search).get('floodPreview') !== '1'
    ) {
      return
    }

    let active = true
    void import('../dev/floodPreview').then(({ floodPreviewEvents: fixtures }) => {
      if (active) setFloodPreviewEvents(fixtures)
    })
    return () => {
      active = false
    }
  }, [])

  /**
   * Split the feed into the two panels.
   *
   * Emergencies sort hardest-first, so the top of the right panel is always
   * the thing most in need of a decision.
   */
  const emergencyEvents = useMemo(
    () => events
      .filter((event) => classify(event) === 'emergency')
      .sort((a, b) => {
        const left = a.type === 'fire' ? a.details.risk_score ?? 0 : 0
        const right = b.type === 'fire' ? b.details.risk_score ?? 0 : 0
        return right - left
      }),
    [events],
  )

  const advisoryEvents = useMemo(
    () => events.filter((event) => classify(event) !== 'emergency'),
    [events],
  )

  const corridorEvent = selectedEvent?.type === 'air_pollution'
    ? selectedEvent
    : null
  const allocationEvents = useMemo(
    () => events.filter(
      (event): event is FireEvent | EarthquakeEvent | FloodEvent => (
        (event.type === 'fire' || event.type === 'earthquake' || event.type === 'flood')
        && (event.details.resource_allocation?.stations.length ?? 0) > 0
      ),
    ),
    [events],
  )
  const openAllocationEvent = openEvent
    ? allocationEvents.find((event) => event.type === openEvent.type && event.id === openEvent.id) ?? null
    : null
  const routesEvent = routesShown ? openAllocationEvent : null
  // Drawn for the selected fire only. Every open fire at once would overlay
  // rings across the country and make the one the operator opened the hardest
  // to read.
  const spreadEvent = selectedEvent?.type === 'fire'
    && selectedEvent.details.spread
    ? selectedEvent
    : null

  /**
   * True while the detection scan is running.
   *
   * The scan takes tens of seconds — satellite lookup, geospatial context and
   * two model calls. Without this the sidebar would read "there are 0 events"
   * for the whole wait, which is indistinguishable from a completed clean scan.
   */
  const [isLoadingEvents, setIsLoadingEvents] =
    useState(true)

  const [leaving, setLeaving] =
    useState(false)


  // =========================================================
  // Layer visibility
  // =========================================================






  const [
    showFireDistricts,
    setShowFireDistricts,
  ] = useState(false)

  const [
    showMdaDistricts,
    setShowMdaDistricts,
  ] = useState(false)

  // Stations and districts are reference data, switched from the "I want to
  // see" bar above the map. Everything else on the map is always on.
  const [
    showFireStations,
    setShowFireStations,
  ] = useState(false)

  const [
    fireStationCount,
    setFireStationCount,
  ] = useState<{ located: number; total: number } | null>(null)

  const [
    showPoliceStations,
    setShowPoliceStations,
  ] = useState(false)

  const [
    policeStationCount,
    setPoliceStationCount,
  ] = useState<{ located: number; total: number } | null>(null)

  const [
    showMdaStations,
    setShowMdaStations,
  ] = useState(false)

  const [
    mdaStationCount,
    setMdaStationCount,
  ] = useState<{ located: number; total: number } | null>(null)

  const [nationalRiskScan, setNationalRiskScan] =
    useState<NationalRiskScan | null>(null)
  const [nationalRiskError, setNationalRiskError] =
    useState<string | null>(null)
  const [focusedFireRiskCluster, setFocusedFireRiskCluster] =
    useState<FireRiskCluster | null>(null)
  const [dismissedFireRiskSnapshot, setDismissedFireRiskSnapshot] =
    useState<string | null>(null)


  const navigate = useNavigate()


  // =========================================================
  // Detected events
  // =========================================================

  // Refetched on mount and again whenever a scenario starts, stops or lands a
  // new wave. A scenario repoints the detectors at authored observations while
  // this page stays open, so the feed has to be re-read rather than loaded once
  // — otherwise the map would keep showing the world the dashboard booted in.
  const loadProjectedEvents = useCallback(() => {
    // An empty list is a valid answer — the pipeline ran and nothing is
    // burning — so this assigns unconditionally rather than only on a truthy
    // list, which would leave stale events on the map after a clean tick.
    void fetch(demo ? '/api/demo/events' : '/api/events')
      .then((response) => {
        if (!response.ok) throw new Error('Projected event feed is unavailable')
        return response.json() as Promise<SharedEventFeed>
      })
      .then((data) => setProjectedEvents(data.events ?? []))
      .catch((error) => console.error('Error fetching projected events:', error))
      .finally(() => setIsLoadingEvents(false))
  }, [demo])

  useEffect(() => {
    loadProjectedEvents()

    // Unverified reports are an operator decision queue. There is nothing to
    // decide in a demo, and a confirm click would write to the live store.
    if (!demo) void loadWeakEvents()
  }, [demo, loadProjectedEvents])

  const loadWeakEvents = () =>
    fetch('/api/weak-events')
      .then((response) => {
        if (!response.ok) throw new Error('Weak event feed is unavailable')
        return response.json() as Promise<WeakEventFeed>
      })
      .then((data) => setWeakEvents(data.weak_events ?? []))
      .catch((error) => console.error('Error fetching weak events:', error))

  const rememberOperator = (name: string) => {
    setOperatorName(name)
    try {
      window.localStorage.setItem('ecoguard.operator', name)
    } catch {
      // A browser with site data blocked still works; the name just does not
      // survive a reload.
    }
  }

  const decideWeakEvent = async (id: string, decision: 'confirm' | 'dismiss') => {
    const response = await fetch(`/api/weak-events/${id}/${decision}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operator: operatorName }),
    })
    if (!response.ok) throw new Error('Decision was not recorded')
    // Drop it locally rather than waiting for the refetch: the operator just
    // acted on it and a card that lingers invites a second click.
    setWeakEvents((current) => current.filter((weak) => weak.id !== id))
  }

  useEffect(() => {
    let active = true
    let requestInFlight = false
    let controller: AbortController | null = null

    const loadNationalRiskScan = async () => {
      if (requestInFlight) return
      requestInFlight = true
      controller = new AbortController()
      try {
        const response = await fetch('/api/fire-risk/national-scan', { signal: controller.signal })
        if (!response.ok) throw new Error('National risk scan is unavailable')
        const scan = normalizeNationalRiskScanResponse(await response.json() as unknown)
        if (active) {
          setNationalRiskScan(scan)
          setNationalRiskError(null)
        }
      } catch (reason: unknown) {
        if (active && !controller.signal.aborted) {
          setNationalRiskError(reason instanceof Error ? reason.message : 'National risk scan is unavailable')
        }
      } finally {
        requestInFlight = false
      }
    }

    void loadNationalRiskScan()
    const intervalId = window.setInterval(() => void loadNationalRiskScan(), 5 * 60 * 1000)
    return () => {
      active = false
      controller?.abort()
      window.clearInterval(intervalId)
    }
  }, [])

  const highRiskClusters = useMemo(
    () => clusterHighRiskCells(nationalRiskScan?.cells ?? []),
    [nationalRiskScan],
  )

  const viewHighRiskOnMap = (cluster: FireRiskCluster) => {
    setFocusedFireRiskCluster(cluster)
  }


  // =========================================================
  // Logout
  // =========================================================

  const handleLogout = () => {
    setLeaving(true)

    setTimeout(
      () => navigate('/'),
      700
    )
  }

  return (
    <MapProvider>
    <main
      className={
        `dashboard${
          leaving
            ? ' dashboard--leaving'
            : ''
        }`
      }
    >

      <header className="dashboard__header">

        <div className="dashboard__brand">
          <svg className="dashboard__leaf" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M5 27C5 13 13 5 28 4c-1 15-9 23-23 23z" />
            <path d="M5 27 19 13" className="dashboard__leaf-vein" />
          </svg>
          <h1 className="dashboard__title">
            <span className="dashboard__eco">Eco</span>Guard
          </h1>
          {!demo && <span className="dashboard__status">Live</span>}
          {!demo && (
            <ScenarioControl
              onStateChange={() => {
                loadProjectedEvents()
                void loadWeakEvents()
              }}
            />
          )}
        </div>

        <EventLegend />

        <button
          type="button"
          className="logout-button"
          onClick={() => navigate('/system', { state: { from: demo ? '/demo' : '/dashboard' } })}
        >
          System
        </button>

        <button
          className="logout-button"
          onClick={handleLogout}
        >
          {demo ? 'Leave demo' : 'Log out'}
        </button>

      </header>


      <div className="dashboard__body">

        <aside className="dashboard__panel dashboard__panel--advisory">

          <div className="panel__header">
            Advisory
            <span className="panel__count">{advisoryEvents.length}</span>
          </div>

          <div className="panel__list">
            {/* Standing on its own above the feed: the lake is a continuous
                state, not an event that starts and ends, so it is always
                shown rather than appearing when something crosses a line. */}
            <KinneretLevelCard />

            {isLoadingEvents && advisoryEvents.length === 0 ? (
              <p className="panel__empty">Scanning…</p>
            ) : advisoryEvents.length === 0 ? (
              <p className="panel__empty">Nothing requiring advice.</p>
            ) : (
              advisoryEvents.map((event) => (
                <EventCard
                  key={event.id}
                  event={event}
                  onOpen={selectAndOpenEvent}
                  isSelected={selectedEvent?.type === event.type && selectedEvent.id === event.id}
                />
              ))
            )}
          </div>

        </aside>


        <div className="dashboard__center">

        <main className="dashboard__map">

          <WhatToSeeControl
            groups={[
              {
                label: 'Stations',
                toggles: [
                    {
                      id: 'fire-stations',
                      label: 'Fire Stations',
                      swatch: { logo: '/FireDepIsrael.svg', ring: '#dc2626' },
                      checked: showFireStations,
                      onToggle: () =>
                        setShowFireStations((current) => !current),
                      note: fireStationCount
                        ? `${fireStationCount.located}/${fireStationCount.total}`
                        : null,
                    },
                    {
                      id: 'police-stations',
                      label: 'Police Stations',
                      swatch: { logo: '/Emblem_of_Israel_Police_Blue.svg', ring: '#1d4ed8' },
                      checked: showPoliceStations,
                      onToggle: () =>
                        setShowPoliceStations((current) => !current),
                      note: policeStationCount
                        ? `${policeStationCount.total}`
                        : null,
                    },
                    {
                      id: 'mda-stations',
                      label: 'MDA Stations',
                      swatch: { logo: '/Mada_logo.svg', ring: '#dc2626' },
                      checked: showMdaStations,
                      onToggle: () =>
                        setShowMdaStations((current) => !current),
                      note: mdaStationCount
                        ? `${mdaStationCount.located}/${mdaStationCount.total}`
                        : null,
                    },
                ],
              },
              {
                label: 'Districts',
                toggles: [
                  {
                    id: 'fire-districts',
                    label: 'Fire Districts',
                    swatch: { logo: '/FireDepIsrael.svg', ring: '#dc2626', area: true },
                    checked: showFireDistricts,
                    onToggle: () =>
                      setShowFireDistricts((current) => !current),
                  },
                  {
                    id: 'mda-districts',
                    label: 'MDA Districts',
                    swatch: { logo: '/Mada_logo.svg', ring: '#dc2626', area: true },
                    checked: showMdaDistricts,
                    onToggle: () =>
                      setShowMdaDistricts((current) => !current),
                  },
                ],
              },
            ]}
          />


          <MapView
            events={events}
            onEventClick={selectAndOpenEvent}
            style={{ flex: '1 1 auto', minHeight: 0 }}
          >

            {nationalRiskScan && highRiskClusters.length > 0 && dismissedFireRiskSnapshot !== nationalRiskScan.evaluation_time && (
              <FireRiskAlert
                clusters={highRiskClusters}
                evaluationTime={nationalRiskScan.evaluation_time}
                snapshotStale={nationalRiskScan.refresh_metadata?.stale === true}
                onViewOnMap={viewHighRiskOnMap}
                onDismiss={() => setDismissedFireRiskSnapshot(nationalRiskScan.evaluation_time)}
              />
            )}

            {showFireDistricts && (
              <FireDistrictsLayer />
            )}

            <MdaDistrictsLayer
              visible={showMdaDistricts}
            />

            <FireStationsLayer
              visible={showFireStations}
              onLoaded={setFireStationCount}
            />

            <PoliceStationsLayer
              visible={showPoliceStations}
              onLoaded={setPoliceStationCount}
            />

            <MdaStationsLayer
              visible={showMdaStations}
              onLoaded={setMdaStationCount}
            />

            {events.some((event) => event.type === 'flood') && (
              <FloodLegend />
            )}

            {focusedFireRiskCluster && (
              <FireRiskLayer
                scan={nationalRiskScan}
                error={nationalRiskError}
                visible={false}
                focusedCluster={focusedFireRiskCluster}
                onClearFocusedCluster={() => setFocusedFireRiskCluster(null)}
              />
            )}

            {corridorEvent?.details.transport?.corridor && (
              <AirPollutionCorridorLayer event={corridorEvent} />
            )}

            {spreadEvent?.details.spread && (
              <FireSpreadLayer key={spreadEvent.id} event={spreadEvent} />
            )}

            {/* The open event's allocated stations and the roads chosen for
                them, glowing — shown from the panel's "Show optimal routes". */}
            {routesEvent && (
              <ResourceAllocationLayer
                key={`${routesEvent.type}:${routesEvent.id}`}
                event={routesEvent}
                onShowDirections={(stationKey) => (
                  showStationDirections(routesEvent, stationKey)
                )}
              />
            )}

            {/* The selected event's settlements: red if affected now,
                yellow if in the path. */}
            <SettlementGlowLayer event={selectedEvent} />

            <FlyToEvent request={flyRequest} />


            {/* ================================================= */}
            {/* Find a town by name                               */}
            {/* ================================================= */}

            <TownSearch />

          </MapView>

        </main>

        {/* The event panel docks under the map and pushes it up as it opens.
            Inert while shut, so its hidden controls are not tab stops. */}
        <div className={`event-dock${panelOpen ? ' event-dock--open' : ''}`} inert={!panelOpen}>
          <div className="event-dock__inner">
            {openEvent && (
              <EventModal
                key={`${openEvent.type}:${openEvent.id}`}
                event={openEvent}
                directionsStationKey={directionsStationKey}
                onClose={closePanel}
                routes={openAllocationEvent ? {
                  shown: routesShown,
                  onToggle: () => {
                    setRoutesShown((current) => !current)
                    setVehiclesShown(false)
                  },
                  vehiclesShown,
                  onToggleVehicles: () => setVehiclesShown((current) => !current),
                } : undefined}
              />
            )}
          </div>
        </div>

        </div>


        <aside className="dashboard__panel dashboard__panel--emergency">

          <div className="panel__header">
            Emergency
            <span className="panel__count">{emergencyEvents.length}</span>
          </div>

          <div className="panel__list">
            {isLoadingEvents && emergencyEvents.length === 0 ? (
              <p className="panel__empty">Scanning…</p>
            ) : emergencyEvents.length === 0 ? (
              <p className="panel__empty">No active emergencies.</p>
            ) : (
              emergencyEvents.map((event) => (
                <EventCard
                  key={event.id}
                  event={event}
                  onOpen={selectAndOpenEvent}
                  isSelected={selectedEvent?.type === event.type && selectedEvent.id === event.id}
                />
              ))
            )}
          </div>

          {weakEvents.length > 0 && (
            <div className="panel__section">
              <div className="panel__header">
                Unverified reports
                <span className="panel__count">{weakEvents.length}</span>
              </div>
              <label className="panel__operator">
                Operator
                <input
                  type="text"
                  value={operatorName}
                  placeholder="your name"
                  onChange={(event) => rememberOperator(event.target.value)}
                />
              </label>
              <div className="panel__list">
                {weakEvents.map((weakEvent) => (
                  <WeakEventCard
                    key={weakEvent.id}
                    weakEvent={weakEvent}
                    operator={operatorName}
                    onDecide={decideWeakEvent}
                  />
                ))}
              </div>
            </div>
          )}

        </aside>

      </div>

    </main>
    </MapProvider>
  )
}


export default Dashboard
