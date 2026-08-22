/**
 * Dashboard page — the main operator view at /dashboard.
 *
 * Responsible for orchestrating the live environmental map.
 */

import {
  useState,
  useEffect,
  type CSSProperties,
} from 'react'

import { useNavigate } from 'react-router-dom'

import MapView from '../components/MapView'

import RainRadarLayer, {
  type RainViewerFrame,
} from '../components/layers/RainRadarLayer'

import FireDangerLayer from '../components/layers/FireDangerLayer'
import WindParticleLayer from '../components/layers/WindParticleLayer'

import FireDangerLegend from '../components/FireDangerLegend'
import InfrastructureLayer from '../components/InfrastructureLayer'
import LayersControl from '../components/LayersControl'
import EnvironmentalDataModal from '../components/EnvironmentalDataModal'

import './visuals/dashboard.css'


export type RiskEvent = {
  id: number
  type: string
  title: string
  description: string
  latitude: number
  longitude: number
  risk_score: number
  risk_level: string
  recommended_units: string[]
  response_plan: string
  explanation: string
}


export type EnvironmentalData = {
  metadata: {
    timestamp: string
    collection_status: string

    services: {
      weather: {
        status: string
        source: string
      }

      geospatial: {
        status: string
        source: string
      }
    }
  }

  location: {
    latitude: number
    longitude: number
  }

  geospatial_context: {
    terrain_type: string
    region_type: string
    vegetation_density: number
    distance_to_water_m: number
    [key: string]: any
  }

  weather: {
    current: {
      temperature_c: number
      humidity_percent: number
      wind_speed_kmh: number
      precipitation_mm: number
      weather_code: number
    }

    forecast: {
      daily: {
        max_temp_c: number[]
        min_temp_c: number[]
        max_wind_speed_kmh: number[]
        precipitation_sum_mm: number[]
      }
    }
  }
}


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
  const [events, setEvents] =
    useState<RiskEvent[]>([])

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
    showWind,
    setShowWind,
  ] = useState(false)

  const [
    showInfrastructure,
    setShowInfrastructure,
  ] = useState(true)


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
    fetch('/api/detected-events')
      .then((response) =>
        response.json()
      )
      .then((data) => {
        if (data.events) {
          setEvents(data.events)
        }
      })
      .catch((error) =>
        console.error(
          'Error fetching events:',
          error
        )
      )
  }, [])


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


  /**
   * Stop radar animation if the radar layer is switched off.
   */
  useEffect(() => {
    if (!showRainRadar) {
      setRainPlaying(false)
    }
  }, [
    showRainRadar,
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

  const fetchEnvironmentalData = (
    latitude: number,
    longitude: number
  ) => {
    const url =
      `/api/environmental-data` +
      `?latitude=${latitude}` +
      `&longitude=${longitude}`

    return fetch(url)
      .then(async (response) => {
        if (!response.ok) {
          let errorMessage =
            `Error ${response.status}`

          try {
            const errorData =
              await response.json()

            if (errorData.detail) {
              errorMessage =
                errorData.detail
            }
          } catch {
            // Keep HTTP status when response is not JSON.
          }

          throw new Error(
            errorMessage
          )
        }

        return response.json()
      })
  }


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
    e: any
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
                setShowRainRadar(
                  (current) =>
                    !current
                )
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

          <div className="Event-summary-header">
            Events summary
          </div>

          <div className="Event-counter">
            there are {events.length} events going on at the moment
          </div>

        </aside>

      </div>


      <div className="dashboard-footer">

        <footer>

          <div className="agent-status-header">
            Agent status
          </div>

          <div className="agent-status-container">
            There are no agents active at the moment
          </div>

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