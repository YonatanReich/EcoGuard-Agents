/**
 * Dashboard page — the main operator view at /dashboard.
 *
 * Responsible for orchestrating the live environmental map.
 */

import {
  useState,
  useEffect,
  useMemo,
  type CSSProperties,
} from 'react'

import { useNavigate } from 'react-router-dom'

import MapView from '../components/MapView'

import RainRadarLayer, {
  type RainViewerFrame,
} from '../components/layers/RainRadarLayer'

import FireDangerLayer from '../components/layers/FireDangerLayer'
import EventCard from '../components/EventCard'
import WeakEventCard from '../components/WeakEventCard'
import EventLegend from '../components/EventLegend'
import EventModal from '../components/EventModal'
import { classify } from '../components/hazards'
import FireRiskLayer from '../components/layers/FireRiskLayer'
import WindParticleLayer from '../components/layers/WindParticleLayer'

import FireDangerLegend from '../components/FireDangerLegend'
import FloodLegend from '../components/FloodLegend'
import FireRiskAlert from '../components/FireRiskAlert'
import KinneretLevelCard from '../components/KinneretLevelCard'
import { clusterHighRiskCells, type FireRiskCluster } from '../components/fireRiskClusters'
import { normalizeNationalRiskScanResponse, type NationalRiskScan } from '../components/fireRiskScan'
import AreaSelect from '../components/AreaSelect'
import LayersControl from '../components/LayersControl'
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
import type { WeakEvent, WeakEventFeed } from '../types/weakEvents'
import {
  type FireEvent,
  type EarthquakeEvent,
  type FloodEvent,
  type SharedEvent,
  type SharedEventFeed,
} from '../types/events'

import './visuals/dashboard.css'


const WIND_MIN_HOURS = -6
const WIND_MAX_HOURS = 12

/**
 * Delay between RainViewer animation frames.
 */
const RAIN_ANIMATION_INTERVAL_MS = 800


/**
 * Format a Unix timestamp using Israel local time.
 */
function formatIsraelTime(
  timestamp: number | null
) {
  if (timestamp === null) {
    return null
  }

  return new Intl.DateTimeFormat(
    'en-GB',
    {
      timeZone: 'Asia/Jerusalem',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }
  ).format(
    new Date(
      timestamp * 1000
    )
  )
}



function Dashboard() {
  const floodTestMode = new URLSearchParams(window.location.search)
    .get('floodTest') === '1'
  const [projectedEvents, setProjectedEvents] =
    useState<SharedEvent[]>([])
  const [floodTestScenario, setFloodTestScenario] =
    useState('confirmed_q10')
  const [floodTestStatus, setFloodTestStatus] =
    useState<string | null>(null)
  const [isRunningFloodTest, setIsRunningFloodTest] =
    useState(false)
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

  /** The event whose modal is open, from either a card or a map marker. */
  const [openEvent, setOpenEvent] =
    useState<SharedEvent | null>(null)
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
  }

  const showStationDirections = (event: SharedEvent, stationKey: string) => {
    setSelectedEventKey(`${event.type}:${event.id}`)
    setDirectionsStationKey(stationKey)
    setOpenEvent(event)
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
        && event.details.resource_allocation !== null
      ),
    ),
    [events],
  )
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
    showRainRadar,
    setShowRainRadar,
  ] = useState(!floodTestMode)

  const [
    showFireDanger,
    setShowFireDanger,
  ] = useState(false)

  const [
    showFireRisk,
    setShowFireRisk,
  ] = useState(false)

  const [
    showFloodEvents,
    setShowFloodEvents,
  ] = useState(true)

  const [
    showWind,
    setShowWind,
  ] = useState(false)

  const [
    showFireDistricts,
    setShowFireDistricts,
  ] = useState(false)

  const [
    showMdaDistricts,
    setShowMdaDistricts,
  ] = useState(false)
  // Stations and routes belong to one operational overlay. Event markers are
  // rendered by MapView and remain visible when this layer is switched off.
  const [
    showAllocations,
    setShowAllocations,
  ] = useState(true)

  // Fire stations are reference data rather than an environmental overlay, so
  // they live in the "I want to see" bar above the map, not in LayersControl.
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


  // =========================================================
  // Wind timeline
  // =========================================================

  /**
   * Wind time offset relative to the current hour.
   *
   * -6 = six hours ago
   *  0 = current
   * +12 = twelve-hour forecast
   */
  const [
    windOffsetHours,
    setWindOffsetHours,
  ] = useState(0)


  /**
   * Actual timestamp selected by Open-Meteo.
   */
  const [
    windTimestamp,
    setWindTimestamp,
  ] = useState<number | null>(null)


  // =========================================================
  // Rain radar timeline
  // =========================================================

  /**
   * All historical radar frames returned by RainViewer.
   */
  const [
    rainFrames,
    setRainFrames,
  ] = useState<RainViewerFrame[]>([])


  /**
   * Currently selected RainViewer frame.
   */
  const [
    rainFrameIndex,
    setRainFrameIndex,
  ] = useState(0)


  /**
   * Timestamp of the radar frame currently shown.
   */
  const [
    rainTimestamp,
    setRainTimestamp,
  ] = useState<number | null>(null)


  /**
   * Whether the radar timeline is currently animating.
   */
  const [
    rainPlaying,
    setRainPlaying,
  ] = useState(false)


  const navigate = useNavigate()


  // =========================================================
  // Detected events
  // =========================================================

  useEffect(() => {
    // No setIsLoadingEvents(true) here: the state already initializes to true
    // and this effect runs once on mount, so setting it again would only
    // trigger a cascading render.
    // An empty list is a valid answer — the pipeline ran and nothing is
    // burning — so this assigns unconditionally rather than only on a truthy
    // list, which would leave stale events on the map after a clean tick.
    void fetch('/api/events')
      .then((response) => {
        if (!response.ok) throw new Error('Projected event feed is unavailable')
        return response.json() as Promise<SharedEventFeed>
      })
      .then((data) => setProjectedEvents(data.events ?? []))
      .catch((error) => console.error('Error fetching projected events:', error))
      .finally(() => setIsLoadingEvents(false))

    if (!floodTestMode) void loadWeakEvents()
  }, [floodTestMode])

  const runFloodTest = async () => {
    setIsRunningFloodTest(true)
    setFloodTestStatus(`Running ${floodTestScenario}… see the API terminal for every stage.`)
    try {
      const response = await fetch(
        `/api/dev/flood-tests/${floodTestScenario}/run`,
        { method: 'POST' },
      )
      if (!response.ok) {
        const failure = await response.json() as { detail?: unknown }
        throw new Error(typeof failure.detail === 'string'
          ? failure.detail
          : JSON.stringify(failure.detail ?? failure))
      }
      const feedResponse = await fetch('/api/events')
      if (!feedResponse.ok) throw new Error('Final event feed is unavailable')
      const feed = await feedResponse.json() as SharedEventFeed
      setProjectedEvents(feed.events ?? [])
      setSelectedEventKey(null)
      setOpenEvent(null)
      setFloodTestStatus(
        feed.events.length > 0
          ? `Complete: ${feed.events.length} active event(s) rendered from /api/events.`
          : floodTestScenario === 'ended'
            ? 'Complete: the event closed after 3h 00m 01s and disappeared from /api/events.'
            : 'Complete: the detector emitted no confirmed event; /api/events is empty.',
      )
    } catch (reason: unknown) {
      setFloodTestStatus(
        `Failed: ${reason instanceof Error ? reason.message : 'unknown error'}`,
      )
    } finally {
      setIsRunningFloodTest(false)
      setIsLoadingEvents(false)
    }
  }

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
    if (floodTestMode) return
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
  }, [floodTestMode])

  const highRiskClusters = useMemo(
    () => clusterHighRiskCells(nationalRiskScan?.cells ?? []),
    [nationalRiskScan],
  )

  const viewHighRiskOnMap = (cluster: FireRiskCluster) => {
    setFocusedFireRiskCluster(cluster)
  }


  // =========================================================
  // Rain radar animation
  // =========================================================

  /**
   * Advance through the cached RainViewer frames while Play is active.
   *
   * No new metadata request is made here.
   * RainRadarLayer already holds the RainViewer frame metadata.
   *
   * When the animation reaches the latest frame, it loops back
   * to the oldest frame.
   */
  useEffect(() => {
    if (
      !rainPlaying ||
      !showRainRadar ||
      rainFrames.length < 2
    ) {
      return
    }

    const intervalId =
      window.setInterval(
        () => {
          setRainFrameIndex(
            (currentIndex) =>
              (
                currentIndex + 1
              ) % rainFrames.length
          )
        },
        RAIN_ANIMATION_INTERVAL_MS
      )

    return () => {
      window.clearInterval(
        intervalId
      )
    }
  }, [
    rainPlaying,
    showRainRadar,
    rainFrames.length,
  ])


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

  const toggleRainRadar = () => {
    if (showRainRadar) setRainPlaying(false)
    setShowRainRadar((current) => !current)
  }


  // =========================================================
  // Wind display calculations
  // =========================================================

  const formattedWindTime =
    formatIsraelTime(
      windTimestamp
    )


  const windTimeMode =
    windOffsetHours === 0
      ? 'Current'
      : windOffsetHours < 0
        ? `${Math.abs(
            windOffsetHours
          )}h ago`
        : `Forecast +${windOffsetHours}h`


  /**
   * Slider position:
   *
   * -6h  = 0%
   * Now  = 33.33%
   * +12h = 100%
   */
  const windSliderPositionPercent =
    (
      (
        windOffsetHours -
        WIND_MIN_HOURS
      ) /
      (
        WIND_MAX_HOURS -
        WIND_MIN_HOURS
      )
    ) * 100


  // =========================================================
  // Rain display calculations
  // =========================================================

  /**
   * Called when RainRadarLayer receives RainViewer metadata.
   *
   * Automatically select the latest radar observation.
   */
  const handleRainFramesChange = (
    frames: RainViewerFrame[]
  ) => {
    setRainFrames(frames)

    if (frames.length > 0) {
      setRainFrameIndex(
        frames.length - 1
      )
    } else {
      setRainFrameIndex(0)
      setRainPlaying(false)
    }
  }


  const formattedRainTime =
    formatIsraelTime(
      rainTimestamp
    )


  const oldestRainTime =
    rainFrames.length > 0
      ? formatIsraelTime(
          rainFrames[0].time
        )
      : null


  const latestRainTime =
    rainFrames.length > 0
      ? formatIsraelTime(
          rainFrames[
            rainFrames.length - 1
          ].time
        )
      : null


  /**
   * Percentage position of the selected radar frame.
   */
  const rainSliderPositionPercent =
    rainFrames.length > 1
      ? (
          rainFrameIndex /
          (
            rainFrames.length - 1
          )
        ) * 100
      : 100


  /**
   * Number of minutes between the selected radar frame
   * and the newest RainViewer observation.
   */
  const rainMinutesAgo =
    rainFrames.length > 0 &&
    rainTimestamp !== null
      ? Math.max(
          0,
          Math.round(
            (
              rainFrames[
                rainFrames.length - 1
              ].time -
              rainTimestamp
            ) / 60
          )
        )
      : 0


  const rainTimeMode =
    rainMinutesAgo === 0
      ? 'Latest'
      : `${rainMinutesAgo}m ago`


  return (
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

        <button
          className="logout-button"
          onClick={handleLogout}
        >
          Log out
        </button>


        <div className="dashboard__header-center">

          <h1 className="dashboard__title">
            EcoGuard Dashboard
          </h1>

          <p className="dashboard__subtitle">
            Live disaster-risk map of Israel
          </p>

        </div>


        <div className="dashboard__header-spacer" />

      </header>


      <EventLegend
        emergencyCount={emergencyEvents.length}
        advisoryCount={advisoryEvents.length}
      />

      {floodTestMode && (
        <section className="flood-test-panel" aria-label="Manual Flood pipeline test">
          <strong>Manual Flood pipeline test</strong>
          <label>
            Scenario
            <select
              value={floodTestScenario}
              onChange={(event) => setFloodTestScenario(event.target.value)}
              disabled={isRunningFloodTest}
            >
              <option value="below_threshold">Below-threshold noise</option>
              <option value="single_q10">Single Q10 reading</option>
              <option value="gap_over_30m">Q10 readings 31m apart</option>
              <option value="below_breaks_sequence">Below Q10 breaks sequence</option>
              <option value="confirmed_q10">Confirmed Q10 event</option>
              <option value="escalated_q20">Escalation Q10 → Q20</option>
              <option value="ended">Event ends after 3 quiet hours</option>
            </select>
          </label>
          <button type="button" onClick={() => void runFloodTest()} disabled={isRunningFloodTest}>
            {isRunningFloodTest ? 'Running…' : 'Run through existing pipeline'}
          </button>
          <span>{floodTestStatus ?? 'Full component output will appear in the API terminal.'}</span>
        </section>
      )}


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


        <main className="dashboard__map">

          <WhatToSeeControl
            toggles={[
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
            ]}
          />

          <MapView
            events={events}
            showFloodEvents={showFloodEvents}
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

            {/* ================================================= */}
            {/* Rain Radar                                        */}
            {/* ================================================= */}

            {showRainRadar && (
              <RainRadarLayer
                selectedFrameIndex={
                  rainFrameIndex
                }
                onFramesChange={
                  handleRainFramesChange
                }
                onFrameTimeChange={
                  setRainTimestamp
                }
              />
            )}


            {showRainRadar &&
              rainFrames.length > 0 && (
                <div
                  style={{
                    ...rainTimelineStyle,

                    /**
                     * If Wind is also visible,
                     * place the radar timeline above it.
                     */
                    bottom:
                      showWind
                        ? 165
                        : 36,
                  }}
                >

                  <div
                    style={
                      rainTimelineHeaderStyle
                    }
                  >

                    <strong>
                      🌧 Rain Radar
                    </strong>


                    <button
                      type="button"
                      style={
                        rainPlayButtonStyle
                      }
                      onClick={() =>
                        setRainPlaying(
                          (current) =>
                            !current
                        )
                      }
                      disabled={
                        rainFrames.length < 2
                      }
                      title={
                        rainPlaying
                          ? 'Pause radar animation'
                          : 'Play radar animation'
                      }
                    >
                      {rainPlaying
                        ? '⏸ Pause'
                        : '▶ Play'}
                    </button>

                  </div>


                  <div
                    style={
                      rainSliderContainerStyle
                    }
                  >

                    {formattedRainTime && (
                      <div
                        style={{
                          ...rainFloatingLabelStyle,

                          left:
                            `${rainSliderPositionPercent}%`,

                          transform:
                            `translateX(-${rainSliderPositionPercent}%)`,
                        }}
                      >
                        {rainTimeMode}
                        {' · '}
                        {formattedRainTime}

                        <div
                          style={
                            rainFloatingArrowStyle
                          }
                        >
                          ▼
                        </div>

                      </div>
                    )}


                    <input
                      type="range"
                      min={0}
                      max={
                        Math.max(
                          rainFrames.length - 1,
                          0
                        )
                      }
                      step={1}
                      value={
                        rainFrameIndex
                      }
                      onChange={(event) => {
                        /**
                         * Manual timeline interaction stops
                         * the automatic radar animation.
                         */
                        setRainPlaying(false)

                        setRainFrameIndex(
                          Number(
                            event.target.value
                          )
                        )
                      }}
                      style={
                        rainSliderStyle
                      }
                    />

                  </div>


                  <div
                    style={
                      rainTimelineLabelsStyle
                    }
                  >

                    <span>
                      {oldestRainTime ??
                        'Oldest'}
                    </span>

                    <span>
                      Past radar
                    </span>

                    <span>
                      {latestRainTime ??
                        'Latest'}
                    </span>

                  </div>

                </div>
              )}


            {/* ================================================= */}
            {/* Wind                                              */}
            {/* ================================================= */}

            {showWind && (
              <WindParticleLayer
                timeOffsetHours={
                  windOffsetHours
                }
                onTimeChange={
                  setWindTimestamp
                }
              />
            )}


            {showWind && (
              <div
                style={
                  windTimelineStyle
                }
              >

                <div
                  style={
                    windTimelineTitleStyle
                  }
                >
                  <strong>
                    💨 Wind
                  </strong>
                </div>


                <div
                  style={
                    windSliderContainerStyle
                  }
                >

                  {formattedWindTime && (
                    <div
                      style={{
                        ...windFloatingLabelStyle,

                        left:
                          `${windSliderPositionPercent}%`,

                        transform:
                          `translateX(-${windSliderPositionPercent}%)`,
                      }}
                    >
                      {windTimeMode}
                      {' · '}
                      {formattedWindTime}

                      <div
                        style={
                          windFloatingArrowStyle
                        }
                      >
                        ▼
                      </div>

                    </div>
                  )}


                  <input
                    type="range"
                    min={
                      WIND_MIN_HOURS
                    }
                    max={
                      WIND_MAX_HOURS
                    }
                    step={3}
                    value={
                      windOffsetHours
                    }
                    onChange={(event) =>
                      setWindOffsetHours(
                        Number(
                          event.target.value
                        )
                      )
                    }
                    style={
                      windSliderStyle
                    }
                  />

                </div>


                <div
                  style={
                    windTimelineLabelsStyle
                  }
                >

                  <span>
                    -6h
                  </span>

                  <span
                    style={{
                      position:
                        'absolute',

                      left:
                        '33.333%',

                      transform:
                        'translateX(-50%)',
                    }}
                  >
                    Now
                  </span>

                  <span>
                    +12h
                  </span>

                </div>

              </div>
            )}


            {/* ================================================= */}
            {/* Fire danger                                       */}
            {/* ================================================= */}

            {showFireDanger && (
              <FireDangerLayer />
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

            {showFireDanger && (
              <FireDangerLegend />
            )}

            {showFloodEvents && events.some((event) => event.type === 'flood') && (
              <FloodLegend fireDangerVisible={showFireDanger} />
            )}

            {(showFireRisk || focusedFireRiskCluster) && (
              <FireRiskLayer
                scan={nationalRiskScan}
                error={nationalRiskError}
                visible={showFireRisk}
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

            {showAllocations && allocationEvents.map((event) => (
              <ResourceAllocationLayer
                key={`${event.type}:${event.id}`}
                event={event}
                onShowDirections={(stationKey) => (
                  showStationDirections(event, stationKey)
                )}
              />
            ))}


            {/* ================================================= */}
            {/* Layer controls                                    */}
            {/* ================================================= */}

            <LayersControl
              showRainRadar={
                showRainRadar
              }
              onToggleRainRadar={toggleRainRadar}

              showFireDanger={
                showFireDanger
              }
              onToggleFireDanger={() =>
                setShowFireDanger(
                  (current) =>
                    !current
                )
              }

              showFireRisk={
                showFireRisk
              }
              onToggleFireRisk={() =>
                setShowFireRisk(
                  (current) =>
                    !current
                )
              }

              showFloodEvents={showFloodEvents}
              onToggleFloodEvents={() =>
                setShowFloodEvents(
                  (current) => !current
                )
              }

              showWind={
                showWind
              }
              onToggleWind={() =>
                setShowWind(
                  (current) =>
                    !current
                )
              }

              showFireDistricts={
                showFireDistricts
              }
              onToggleFireDistricts={() =>
                setShowFireDistricts(
                  (current) =>
                    !current
                )
              }

              showMdaDistricts={
                showMdaDistricts
              }
              onToggleMdaDistricts={() =>
                setShowMdaDistricts(
                  (current) =>
                    !current
                )
              }
              showAllocations={
                showAllocations
              }
              onToggleAllocations={() =>
                setShowAllocations(
                  (current) =>
                    !current
                )
              }

            />


            {/* ================================================= */}
            {/* Find a town by name                               */}
            {/* ================================================= */}

            <TownSearch />


            {/* ================================================= */}
            {/* Draw an area, read what is inside it              */}
            {/* ================================================= */}

            <AreaSelect />

          </MapView>

        </main>


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


      {openEvent && (
        <EventModal
          key={`${openEvent.type}:${openEvent.id}`}
          event={openEvent}
          directionsStationKey={directionsStationKey}
          onClose={() => {
            setOpenEvent(null)
            setDirectionsStationKey(null)
          }}
        />
      )}

    </main>
  )
}


// ===========================================================
// Wind timeline styles
// ===========================================================

const windTimelineStyle: CSSProperties = {
  position: 'absolute',

  bottom: 36,

  right: 12,

  zIndex: 5,

  width: 300,

  background:
    'rgba(255, 255, 255, 0.96)',

  color: '#111827',

  padding: '10px 12px',

  borderRadius: 10,

  boxShadow:
    '0 2px 10px rgba(0, 0, 0, 0.22)',
}


const windTimelineTitleStyle: CSSProperties = {
  fontSize: '0.82rem',

  marginBottom: 32,
}


const windSliderContainerStyle: CSSProperties = {
  position: 'relative',

  width: '100%',
}


const windFloatingLabelStyle: CSSProperties = {
  position: 'absolute',

  bottom: 28,

  whiteSpace: 'nowrap',

  background: '#ffffff',

  color: '#111827',

  padding: '3px 6px',

  borderRadius: 6,

  fontSize: '0.72rem',

  fontWeight: 600,

  boxShadow:
    '0 1px 4px rgba(0, 0, 0, 0.16)',

  pointerEvents: 'none',

  textAlign: 'center',
}


const windFloatingArrowStyle: CSSProperties = {
  position: 'absolute',

  left: '50%',

  transform:
    'translateX(-50%)',

  bottom: -10,

  fontSize: '0.55rem',

  color: '#6b7280',
}


const windSliderStyle: CSSProperties = {
  width: '100%',

  cursor: 'pointer',

  margin: 0,
}


const windTimelineLabelsStyle: CSSProperties = {
  position: 'relative',

  display: 'flex',

  justifyContent:
    'space-between',

  fontSize: '0.7rem',

  color: '#6b7280',

  marginTop: 5,
}


// ===========================================================
// Rain timeline styles
// ===========================================================

const rainTimelineStyle: CSSProperties = {
  position: 'absolute',

  right: 12,

  zIndex: 5,

  width: 300,

  background:
    'rgba(255, 255, 255, 0.96)',

  color: '#111827',

  padding: '10px 12px',

  borderRadius: 10,

  boxShadow:
    '0 2px 10px rgba(0, 0, 0, 0.22)',

  transition:
    'bottom 0.2s ease',
}


const rainTimelineHeaderStyle: CSSProperties = {
  display: 'flex',

  alignItems: 'center',

  justifyContent:
    'space-between',

  gap: 10,

  marginBottom: 32,

  fontSize: '0.82rem',
}


const rainPlayButtonStyle: CSSProperties = {
  border:
    '1px solid #d1d5db',

  background:
    '#ffffff',

  color:
    '#111827',

  padding:
    '4px 8px',

  borderRadius:
    6,

  fontSize:
    '0.72rem',

  fontWeight:
    600,

  cursor:
    'pointer',
}


const rainSliderContainerStyle: CSSProperties = {
  position: 'relative',

  width: '100%',
}


const rainFloatingLabelStyle: CSSProperties = {
  position: 'absolute',

  bottom: 28,

  whiteSpace: 'nowrap',

  background: '#ffffff',

  color: '#111827',

  padding: '3px 6px',

  borderRadius: 6,

  fontSize: '0.72rem',

  fontWeight: 600,

  boxShadow:
    '0 1px 4px rgba(0, 0, 0, 0.16)',

  pointerEvents: 'none',

  textAlign: 'center',
}


const rainFloatingArrowStyle: CSSProperties = {
  position: 'absolute',

  left: '50%',

  transform:
    'translateX(-50%)',

  bottom: -10,

  fontSize: '0.55rem',

  color: '#6b7280',
}


const rainSliderStyle: CSSProperties = {
  width: '100%',

  cursor: 'pointer',

  margin: 0,
}


const rainTimelineLabelsStyle: CSSProperties = {
  display: 'flex',

  alignItems: 'center',

  justifyContent:
    'space-between',

  fontSize: '0.7rem',

  color: '#6b7280',

  marginTop: 5,
}


export default Dashboard
