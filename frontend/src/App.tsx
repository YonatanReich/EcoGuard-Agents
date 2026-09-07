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
import ArchitectureLayout from './components/ArchitectureLayout'
import { architectureRoutes } from './navigation/architectureRoutes'
import Home from './pages/Home'
import Dashboard from './pages/Dashboard'
import DataCollectionLayers from './pages/DataCollectionLayers'
import EventDetectionWorkspace from './pages/EventDetectionWorkspace'
import ResponsePlanning from './pages/ResponsePlanning'
import ExplanationAudit from './pages/ExplanationAudit'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route element={<ArchitectureLayout />}>
        {architectureRoutes.map((route) => (
          <Route
            key={route.path}
            path={route.path}
            element={
              route.id === 'dashboard'
                ? <Dashboard />
                : route.id === 'data-layers'
                  ? <DataCollectionLayers />
                  : route.id === 'event-detection'
                    ? <EventDetectionWorkspace />
                    : route.id === 'response-planning'
                      ? <ResponsePlanning />
                      : route.id === 'explanation-audit'
                        ? <ExplanationAudit />
                        : null
            }
          />
        ))}
      </Route>
    </Routes>
  )
}

export default App
