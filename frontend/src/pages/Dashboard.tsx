/**
 * Dashboard page — the main operator view at /dashboard.
 *
 * Responsible for orchestrating the whole live view: it owns all page state,
 * talks to the backend, and hands data down to the presentational children.
 * MapView renders the map and markers; EnvironmentalDataModal renders the
 * popup. Neither fetches anything itself.
 *
 * Data flow:
 *   1. On mount, load detected events once and render them as map markers.
 *   2. When the user clicks a point inside Israel, fetch environmental data
 *      for that coordinate and open a popup anchored there.
 *
 * This file also exports the two API response types (RiskEvent and
 * EnvironmentalData) that the child components import, so the backend
 * contract is described in one place.
 *
 * Requests go to relative /api/... paths, which Vite proxies to the FastAPI
 * server in development (see vite.config.ts).
 */

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import MapView from '../components/MapView'
import EnvironmentalDataModal from '../components/EnvironmentalDataModal'
import './visuals/dashboard.css'

/**
 * One detected risk event, as returned by GET /api/detected-events.
 *
 * Combines the event's identity and position with the risk analysis agent's
 * assessment of it. `risk_level` drives the marker colour on the map.
 */
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

/**
 * Unified environmental record for one coordinate, as returned by
 * GET /api/environmental-data.
 *
 * Merges two independent upstream providers, which is why `metadata.services`
 * reports a status per provider: a "partial_service_failure" overall status
 * means one of them is down and the corresponding section will be empty.
 *
 * The daily forecast fields are parallel arrays — index i of each array
 * describes the same day.
 */
export type EnvironmentalData = {
  metadata: {
    timestamp: string
    /** "success" | "partial_service_failure" — overall collection outcome. */
    collection_status: string
    /** Per-provider health, so the UI can tell which half of the data is missing. */
    services: {
      weather: { status: string; source: string }
      geospatial: { status: string; source: string }
    }
  }
  location: {
    latitude: number
    longitude: number
  }
  /**
   * Nearby features and terrain description. The named fields are not yet
   * populated by the backend and currently arrive as null. The index
   * signature covers the nearby_* arrays (roads, settlements, hospitals,
   * police stations, fire stations) which are not yet rendered.
   */
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
    /** Multi-day outlook. Each array holds one value per forecast day. */
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

function Dashboard() {
  /** Detected risk events, rendered as coloured markers on the map. */
  const [events, setEvents] = useState<RiskEvent[]>([])

  /** True once the user has logged out; triggers the leaving CSS effects. */
  const [leaving, setLeaving] = useState(false)

  // Environmental data for the currently selected point, plus the two states
  // that describe the request around it. Exactly one of envData /
  // isLoadingEnvData / envDataError is meaningful at a time — the modal picks
  // which of the three to display.
  const [envData, setEnvData] = useState<EnvironmentalData | null>(null)
  const [isLoadingEnvData, setIsLoadingEnvData] = useState(false)
  const [envDataError, setEnvDataError] = useState<string | null>(null)

  /** The coordinate the user last clicked. Also positions the map marker. */
  const [selectedLocation, setSelectedLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [isPopupOpen, setIsPopupOpen] = useState(false)

  const navigate = useNavigate()

  // Load detected events once on mount. The empty dependency array means this
  // never refetches — events are static for the lifetime of the page.
  useEffect(() => {
    fetch('/api/detected-events')
      .then((response) => response.json())
      .then((data) => {
        if (data.events) {
          setEvents(data.events)
        }
      })
      .catch((error) => console.error('Error fetching events:', error))
  }, [])

  /**
   * Play the exit animation, then return to the landing page.
   *
   * The 700ms delay matches the .dashboard--leaving transition in
   * dashboard.css; keep the two in step if either changes.
   */
  const handleLogout = () => {
    setLeaving(true)
    setTimeout(() => navigate('/'), 700)
  }

  /**
   * Request environmental data for one coordinate.
   *
   * Pure fetch helper — it does not touch component state. On a non-OK
   * response it unwraps FastAPI's error format so the user sees the backend's
   * actual message (for example "Error fetching data.") rather than a bare
   * status code.
   *
   * @returns Promise resolving to the parsed EnvironmentalData, or rejecting
   *          with an Error carrying a display-ready message.
   */
  const fetchEnvironmentalData = (latitude: number, longitude: number) => {
    const url = `/api/environmental-data?latitude=${latitude}&longitude=${longitude}`
    
    return fetch(url).then(async (response) => {
      if (!response.ok) {
        let errorMessage = `Error ${response.status}`
        
        try {
          // FastAPI packages the error message inside a "detail" property
          const errorData = await response.json()
          if (errorData.detail) {
            // Extracting the specific message from the backend
            errorMessage = errorData.detail
          }
        } catch (e) {
          // If the server didn't send JSON (e.g., a total crash), we keep the status code
        }
        
        throw new Error(errorMessage)
      }
      return response.json()
    })
  }

  /**
   * Fetch environmental data for a coordinate and drive the loading, success
   * and error state the modal renders from.
   *
   * Clears any previous result and error up front so a slow request never
   * shows stale data from the previously clicked point alongside the spinner.
   *
   * Note this request can take several seconds — the backend's geospatial
   * lookup is slow — so the loading state is genuinely visible to the user.
   */
  const loadEnvironmentalData = (latitude: number, longitude: number) => {
    setIsLoadingEnvData(true)
    setEnvDataError(null)
    setEnvData(null)

    fetchEnvironmentalData(latitude, longitude)
      .then((data) => {
        setEnvData(data)
      })
      .catch((error) => {
        setEnvDataError(error.message || 'Error loading data')
      })
      .finally(() => {
        setIsLoadingEnvData(false)
      })
  }

  /**
   * Handle a click on the map: place the marker, open the popup and load
   * data for the clicked point.
   *
   * Also fired synthetically by MapView when an existing event marker is
   * clicked, passing that event's coordinates.
   *
   * @param e Map click event carrying an `lngLat` coordinate.
   */
  const handleMapClick = (e: any) => {
    if (!e.lngLat) return

    const { lat, lng } = e.lngLat

    // Reject clicks outside Israel before spending a request on them. These
    // bounds mirror the validation on the backend's Query parameters, which
    // would reject the same coordinates with a 422 — checking here keeps the
    // popup from opening only to show an error.
    if (lat < 29.45 || lat > 33.35 || lng < 34.26 || lng > 35.90) {
      console.warn('Clicked outside Israel borders. Ignoring.')
      return
    }

    setSelectedLocation({ lat, lng })
    setIsPopupOpen(true)
    loadEnvironmentalData(lat, lng)
  }

  return (
    <main className={`dashboard${leaving ? ' dashboard--leaving' : ''}`}>
      <header className="dashboard__header">
        <button className="logout-button" onClick={handleLogout}>Log out</button>
        <div className="dashboard__header-center">
          <h1 className="dashboard__title">EcoGuard Dashboard</h1>
          <p className="dashboard__subtitle">Live disaster-risk map of Israel</p>
        </div>
        <div className="dashboard__header-spacer" />
      </header>
      <div className="dashboard__body">
        {/* The modal is nested inside MapView because it renders as a
            maplibre Popup, which must live within the Map's context to
            anchor itself to a coordinate. */}
        <main className="dashboard__map">
          <MapView 
            events={events}
            onClick={handleMapClick}
            selectedLocation={selectedLocation} 
          >
            <EnvironmentalDataModal 
              isOpen={isPopupOpen}
              onClose={() => setIsPopupOpen(false)}
              latitude={selectedLocation?.lat ?? null}
              longitude={selectedLocation?.lng ?? null}
              envData={envData}
              isLoading={isLoadingEnvData}
              error={envDataError}
            />
          </MapView>
        </main>
        <aside className="dashboard__sidebar">
          <div className="Event-summary-header">
            Events summary
          </div>
          <div className='Event-counter'>
            there are {events.length} events going on at the moment
          </div>
        </aside>
      </div>
      <div className="dashboard-footer">
        <footer>
          <div className='agent-status-header'>
            Agent status
          </div>
          <div className='agent-status-container'>
            There are no agents active at the moment
          </div>
        </footer>
      </div>
    </main>
  )
}

export default Dashboard
