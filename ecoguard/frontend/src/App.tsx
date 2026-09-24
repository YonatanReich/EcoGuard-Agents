/**
 * Application root.
 *
 * Responsible for the route table and nothing else. Each route maps a URL to
 * a page component; pages own their own data fetching and layout.
 *
 * Routes:
 *   /           Home — the landing screen, with the Monitor entry button.
 *   /dashboard  Dashboard — the live map and environmental data view.
 *   /demo       Dashboard again, reading fabricated incidents instead of the
 *               live feed, so the allocator and the response plans can be
 *               shown working on demand.
 *   /system     System — every pipeline actor, lit while it is running.
 *
 * Note there is no auth guard: /dashboard is reachable directly by URL. The
 * "Monitor" button is a navigation trigger, not a credential check.
 */

import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Dashboard from './pages/Dashboard'
import System from './pages/System'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/demo" element={<Dashboard demo />} />
      <Route path="/system" element={<System />} />
    </Routes>
  )
}

export default App
