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

import { Link, useNavigate } from 'react-router-dom'

import MapView, { type MapCoordinateClickEvent } from '../components/MapView'

import RainRadarLayer, {
  type RainViewerFrame,
} from '../components/layers/RainRadarLayer'

import FireDangerLayer from '../components/layers/FireDangerLayer'
import FireRiskLayer from '../components/layers/FireRiskLayer'
import WindParticleLayer from '../components/layers/WindParticleLayer'

import FireDangerLegend from '../components/FireDangerLegend'
import FireRiskAlert from '../components/FireRiskAlert'
import { clusterHighRiskCells, type FireRiskCluster } from '../components/fireRiskClusters'
import InfrastructureLayer from '../components/InfrastructureLayer'
import LayersControl from '../components/LayersControl'
import EnvironmentalDataModal from '../components/EnvironmentalDataModal'
import { fetchDetectedEvents } from '../api/detectedEvents'
import { fetchEnvironmentalData } from '../api/environmentalData'
import { useNationalRiskScan } from '../hooks/useNationalRiskScan'
import type { EnvironmentalData } from '../types/environmentalData'
import type { IncidentDetails } from '../types/incidents'

import './visuals/dashboard.css'


const WIND_MIN_HOURS = -6
const WIND_MAX_HOURS = 12

/**
 * Delay between RainViewer animation frames.
 */
const RAIN_ANIMATION_INTERVAL_MS = 800

const OFFICIAL_AGENT_ROLES = [
  'Data Collection Agent',
  'Event Detection Agent',
  'Risk Analysis Agent',
  'Resource Allocation Agent',
  'Response Planning Agent',
  'LLM Coordination Agent',
] as const

const WORKSPACE_LINKS = [
  { path: '/data-layers', label: 'Inspect data & layers' },
  { path: '/event-detection', label: 'Review event evidence' },
  { path: '/response-planning', label: 'Open response planning' },
  { path: '/explanation-audit', label: 'Review explanation & audit' },
] as const


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


/**
 * Sidebar card for one detected event.
 *
 * Renders the assessment, the plan, and — importantly — the protocol passages
 * the reasoning actually cited. Showing the verbatim quote and its source is
 * what lets a reader confirm the analysis was grounded in the corpus rather
 * than taking the claim on trust.
 */
function EventSummaryCard({ event }: { event: IncidentDetails }) {
  const hasAssessment =
    event.analysis_status === 'success' &&
    event.risk_score != null
  const primaryDrivers = event.primary_drivers ?? []
  const responseActions = event.response_actions ?? []
  const evidenceGaps = event.evidence_gaps ?? []
  const protocolCitations = event.protocol_citations ?? []

  return (
    <article className="event-card">

      <header className="event-card__header">
        <span
          className={`event-card__badge event-card__badge--${event.risk_level ?? 'unknown'}`}
        >
          {hasAssessment
            ? `${event.risk_level} · ${event.risk_score}`
            : 'not assessed'}
        </span>
        <h3 className="event-card__title">{event.title}</h3>
      </header>

      {/* An unassessed event is stated plainly rather than shown with a
          default score. A fabricated "low" would read as an all-clear. */}
      {!hasAssessment && (
        <p className="event-card__warning">
          Risk analysis {event.analysis_status ?? 'status unavailable'}. The event was
          detected, but no risk score is available for it.
        </p>
      )}

      {event.explanation && (
        <p className="event-card__text">{event.explanation}</p>
      )}

      {primaryDrivers.length > 0 && (
        <ul className="event-card__drivers">
          {primaryDrivers.map((driver) => (
            <li key={driver}>{driver}</li>
          ))}
        </ul>
      )}

      {responseActions.length > 0 && (
        <>
          <h4 className="event-card__subheading">Response plan</h4>
          <ol className="event-card__actions">
            {responseActions.map((action) => (
              <li key={action.action}>
                <span className="event-card__timeframe">
                  {action.timeframe.replace(/_/g, ' ')}
                </span>
                {' '}
                <strong>{action.responsible_unit.replace(/_/g, ' ')}</strong>
                {' — '}
                {action.action}
              </li>
            ))}
          </ol>
        </>
      )}

      {evidenceGaps.length > 0 && (
        <>
          <h4 className="event-card__subheading">Evidence gaps</h4>
          <ul className="event-card__gaps">
            {evidenceGaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </>
      )}

      {protocolCitations.length > 0 && (
        <>
          <h4 className="event-card__subheading">
            Grounded in {protocolCitations.length} protocol passage
            {protocolCitations.length === 1 ? '' : 's'}
          </h4>
          {protocolCitations.map((citation) => (
            <blockquote key={citation.chunk_id} className="event-card__citation">
              <p className="event-card__quote">“{citation.quoted_text}”</p>
              <footer className="event-card__source">
                {citation.source_url ? (
                  <a href={citation.source_url} target="_blank" rel="noreferrer">
                    {citation.document_title}
                  </a>
                ) : (
                  citation.document_title
                )}
                {citation.heading_path && ` · ${citation.heading_path}`}
              </footer>
            </blockquote>
          ))}
        </>
      )}

      <Link className="event-card__workspace-link" to="/event-detection">
        Review event evidence
      </Link>

    </article>
  )
}


function Dashboard() {
  const [events, setEvents] =
    useState<IncidentDetails[]>([])

  /**
   * True while the detection scan is running.
   *
   * The scan takes tens of seconds — satellite lookup, geospatial context and
   * two model calls. Without this the sidebar would read "there are 0 events"
   * for the whole wait, which is indistinguishable from a completed clean scan.
   */
  const [isLoadingEvents, setIsLoadingEvents] =
    useState(true)
  const [eventsError, setEventsError] =
    useState<string | null>(null)

  const [leaving, setLeaving] =
    useState(false)


  // =========================================================
  // Layer visibility
  // =========================================================

  const [
    showRainRadar,
    setShowRainRadar,
  ] = useState(true)

  const [
    showFireDanger,
    setShowFireDanger,
  ] = useState(false)

  const [
    showFireRisk,
    setShowFireRisk,
  ] = useState(false)

  const [
    showWind,
    setShowWind,
  ] = useState(false)

  const [
    showInfrastructure,
    setShowInfrastructure,
  ] = useState(true)

  const {
    scan: nationalRiskScan,
    error: nationalRiskError,
  } = useNationalRiskScan()
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


  // =========================================================
  // Environmental data
  // =========================================================

  const [
    envData,
    setEnvData,
  ] = useState<EnvironmentalData | null>(null)

  const [
    isLoadingEnvData,
    setIsLoadingEnvData,
  ] = useState(false)

  const [
    envDataError,
    setEnvDataError,
  ] = useState<string | null>(null)

  const [
    selectedLocation,
    setSelectedLocation,
  ] = useState<{
    lat: number
    lng: number
  } | null>(null)

  const [
    isPopupOpen,
    setIsPopupOpen,
  ] = useState(false)


  const navigate = useNavigate()


  // =========================================================
  // Detected events
  // =========================================================

  useEffect(() => {
    let active = true

    void fetchDetectedEvents()
      .then((detectedEvents) => {
        if (active) setEvents(detectedEvents)
      })
      .catch((reason: unknown) => {
        if (!active) return
        setEventsError(
          reason instanceof Error
            ? reason.message
            : 'Detected event data is unavailable',
        )
      })
      .finally(() => {
        if (active) setIsLoadingEvents(false)
      })

    return () => {
      active = false
    }
  }, [])

  const highRiskClusters = useMemo(
    () => clusterHighRiskCells(nationalRiskScan?.cells ?? []),
    [nationalRiskScan],
  )

  const viewHighRiskOnMap = (cluster: FireRiskCluster) => {
    setFocusedFireRiskCluster(cluster)
  }

  const primaryEvent = events[0] ?? null
  const recommendationActions = primaryEvent?.response_actions?.length
    ? primaryEvent.response_actions.map((action) => action.action)
    : primaryEvent
      ? Array.isArray(primaryEvent.response_plan)
        ? primaryEvent.response_plan
        : primaryEvent.response_plan
          ? [primaryEvent.response_plan]
          : []
      : []
  const hasGroundedPlan =
    primaryEvent?.planning_status === 'success' &&
    (primaryEvent.response_actions?.length ?? 0) > 0


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


  // =========================================================
  // Environmental data
  // =========================================================

  const loadEnvironmentalData = (
    latitude: number,
    longitude: number
  ) => {
    setIsLoadingEnvData(true)
    setEnvDataError(null)
    setEnvData(null)

    fetchEnvironmentalData(
      latitude,
      longitude
    )
      .then((data) => {
        setEnvData(data)
      })
      .catch((error) => {
        setEnvDataError(
          error.message ||
          'Error loading data'
        )
      })
      .finally(() => {
        setIsLoadingEnvData(false)
      })
  }


  const handleMapClick = (
    e: MapCoordinateClickEvent
  ) => {
    if (!e.lngLat) {
      return
    }

    const {
      lat,
      lng,
    } = e.lngLat

    if (
      lat < 29.45 ||
      lat > 33.35 ||
      lng < 34.26 ||
      lng > 35.90
    ) {
      console.warn(
        'Clicked outside Israel borders. Ignoring.'
      )

      return
    }

    setSelectedLocation({
      lat,
      lng,
    })

    setIsPopupOpen(true)

    loadEnvironmentalData(
      lat,
      lng
    )
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


      <div className="dashboard__body">

        <main className="dashboard__map">

          <MapView
            events={events}
            onClick={handleMapClick}
            selectedLocation={selectedLocation}
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

            {showFireDanger && (
              <FireDangerLegend />
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


            {/* ================================================= */}
            {/* Nearby infrastructure                             */}
            {/* ================================================= */}

            {showInfrastructure &&
              envData && (
                <InfrastructureLayer
                  hospitals={
                    envData
                      .geospatial_context
                      .nearby_hospitals ??
                    []
                  }
                  policeStations={
                    envData
                      .geospatial_context
                      .nearby_police_stations ??
                    []
                  }
                  fireStations={
                    envData
                      .geospatial_context
                      .nearby_fire_stations ??
                    []
                  }
                />
              )}


            {/* ================================================= */}
            {/* Layer controls                                    */}
            {/* ================================================= */}

            <LayersControl
              showRainRadar={
                showRainRadar
              }
              onToggleRainRadar={() =>
                {
                  if (showRainRadar) {
                    setRainPlaying(false)
                  }

                  setShowRainRadar(
                    (current) =>
                      !current
                  )
                }
              }

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

              showWind={
                showWind
              }
              onToggleWind={() =>
                setShowWind(
                  (current) =>
                    !current
                )
              }

              showInfrastructure={
                showInfrastructure
              }
              onToggleInfrastructure={() =>
                setShowInfrastructure(
                  (current) =>
                    !current
                )
              }
            />


            <EnvironmentalDataModal
              isOpen={
                isPopupOpen
              }
              onClose={() =>
                setIsPopupOpen(
                  false
                )
              }
              latitude={
                selectedLocation
                  ?.lat ?? null
              }
              longitude={
                selectedLocation
                  ?.lng ?? null
              }
              envData={
                envData
              }
              isLoading={
                isLoadingEnvData
              }
              error={
                envDataError
              }
            />

          </MapView>

        </main>


        <aside className="dashboard__sidebar">

          <section className="dashboard-summary" aria-labelledby="active-incidents-title">
            <div className="dashboard-summary__heading">
              <h2 id="active-incidents-title">Active incidents</h2>
              <span>{events.length}</span>
            </div>
            {isLoadingEvents && (
              <p className="dashboard-summary__notice">
                Scanning for detected environmental events. Analysis may take up to 90 seconds.
              </p>
            )}
            {eventsError && (
              <p className="dashboard-summary__error" role="alert">
                Detection scan unavailable: {eventsError}
              </p>
            )}
            <div className="dashboard-incident-list">
              {!isLoadingEvents && !eventsError && events.length === 0 && (
                <p className="dashboard-summary__empty">
                  The current detection scan returned no active incidents.
                </p>
              )}
              {!isLoadingEvents && events.map((event) => (
                <EventSummaryCard key={event.id} event={event} />
              ))}
            </div>
          </section>

          <section className="dashboard-summary" aria-labelledby="risk-outlook-title">
            <h2 id="risk-outlook-title">Risk outlook</h2>
            <p>
              National current risk is a conditions-based estimate, not a detected incident.
            </p>
            <div className="dashboard-risk-status">
              <span>Status</span>
              <strong>{nationalRiskError || nationalRiskScan?.status || 'Loading'}</strong>
            </div>
            {nationalRiskScan && (
              <div className="dashboard-risk-status">
                <span>High-risk areas</span>
                <strong>{highRiskClusters.length}</strong>
              </div>
            )}
            <Link className="dashboard-summary__link" to="/data-layers">
              Inspect source details
            </Link>
          </section>

          <section className="dashboard-summary" aria-labelledby="recommendation-title">
            <h2 id="recommendation-title">Recommendation summary</h2>
            {recommendationActions.length > 0 ? (
              <>
                <p className="dashboard-summary__notice">
                  {hasGroundedPlan
                    ? 'Grounded response-planning output. Operator verification is still required.'
                    : 'Legacy or provisional response information—not a verified operational instruction.'}
                </p>
                <ol className="dashboard-recommendations">
                  {recommendationActions.slice(0, 2).map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ol>
              </>
            ) : (
              <p className="dashboard-summary__empty">
                No trustworthy operational recommendation is available.
              </p>
            )}
            <Link className="dashboard-summary__link" to="/response-planning">
              Open response workspace
            </Link>
          </section>

        </aside>

      </div>

      <div className="dashboard-footer">
        <footer className="dashboard-footer__content">
          <section aria-labelledby="agent-status-title">
            <div className="dashboard-footer__heading">
              <h2 id="agent-status-title">Agent status</h2>
              <span>Runtime status is not exposed by the backend</span>
            </div>
            <div className="dashboard-agent-grid">
              {OFFICIAL_AGENT_ROLES.map((role) => (
                <div className="dashboard-agent" key={role}>
                  <strong>{role}</strong>
                  <span>
                    {role === 'Data Collection Agent' && envData
                      ? `Latest context request: ${envData.metadata.collection_status}`
                      : 'Not observed'}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <nav className="dashboard-workflow" aria-label="Incident workflow">
            <h2>Continue workflow</h2>
            <div className="dashboard-workflow__links">
              {WORKSPACE_LINKS.map((workspace) => (
                <Link key={workspace.path} to={workspace.path}>{workspace.label}</Link>
              ))}
            </div>
          </nav>
        </footer>
      </div>
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
