/**
 * Application root.
 *
 * Responsible for the route table and nothing else. Each route maps a URL to
 * a page component; pages own their own data fetching and layout.
 *
 * Routes:
 *   /           Home — the landing and login screen.
 *   /dashboard  Dashboard — the live map and environmental data view.
 *
 * Note there is no auth guard: /dashboard is reachable directly by URL. The
 * "log in" button is presentational for now.
 */

import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Dashboard from './pages/Dashboard'
import Incident3DView from './components/Incident3DView'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/dashboard" element={<Dashboard />} />

      {/* Experimental 3D incident view */}
      <Route path="/incident-3d" element={<Incident3DView />} />
    </Routes>
  )
}

export default App