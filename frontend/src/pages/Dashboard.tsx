import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import MapView from '../components/MapView'
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
      weather: { status: string; source: string }
      geospatial: { status: string; source: string }
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

function Dashboard() {
  //Track environmental events happening now
  const [events, setEvents] = useState<RiskEvent[]>([])
  //This state tracks if the user has logged out, if so, it triggers the leaving CSS effects
  const [leaving, setLeaving] = useState(false)
  // Store environmental data
  const [envData, setEnvData] = useState<EnvironmentalData | null>(null)
  const [isLoadingEnvData, setIsLoadingEnvData] = useState(false)
  const [envDataError, setEnvDataError] = useState<string | null>(null)
  const [selectedEvent, setSelectedEvent] = useState<RiskEvent | null>(null)
  const [isPopupOpen, setIsPopupOpen] = useState(false)
  const navigate = useNavigate()

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

  //This handles logging out back to the main screen
  const handleLogout = () => {
    setLeaving(true)
    setTimeout(() => navigate('/'), 700)
  }

    const fetchEnvironmentalData = (latitude: number, longitude: number) => {
    const url = `/api/environmental-data?latitude=${latitude}&longitude=${longitude}`
    
    return fetch(url)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`${response.status}`)
        }
        return response.json()
      })
  }

  const loadEnvironmentalData = (latitude: number, longitude: number) => {
    setIsLoadingEnvData(true)
    setEnvDataError(null)

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
        <main className="dashboard__map">
          <MapView events={events} />
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
