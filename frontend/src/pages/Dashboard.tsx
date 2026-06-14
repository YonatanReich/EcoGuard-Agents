import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import MapView from '../components/MapView'
import './visuals/dashboard.css'

function Dashboard() {
  //Track how many environmental events are going on
  const [numOfEvents, setNumOfEvents] = useState(0)
  //This state tracks if the user has logged out, if so, it triggers the leaving CSS effects
  const [leaving, setLeaving] = useState(false)
  const navigate = useNavigate()
  //This handles logging out back to the main screen
  const handleLogout = () => {
    setLeaving(true)
    setTimeout(() => navigate('/'), 700)
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
          <MapView />
        </main>
        <aside className="dashboard__sidebar">
          <div className="Event-summary-header">
            Events summary
          </div>
          <div className='Event-counter'>
            there are {numOfEvents} events going on at the moment
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
