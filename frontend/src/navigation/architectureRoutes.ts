export type ArchitectureRoute = {
  id:
    | 'dashboard'
    | 'data-layers'
    | 'event-detection'
    | 'response-planning'
    | 'explanation-audit'
  path: string
  title: string
  navigationLabel: string
}

/** Canonical, event-type-neutral definitions for EcoGuard workspaces. */
export const architectureRoutes: readonly ArchitectureRoute[] = [
  {
    id: 'dashboard',
    path: '/dashboard',
    title: 'Dashboard',
    navigationLabel: 'Dashboard',
  },
  {
    id: 'data-layers',
    path: '/data-layers',
    title: 'Data Collection & Layers',
    navigationLabel: 'Data Collection & Layers',
  },
  {
    id: 'event-detection',
    path: '/event-detection',
    title: 'Event Detection Workspace',
    navigationLabel: 'Event Detection',
  },
  {
    id: 'response-planning',
    path: '/response-planning',
    title: 'Response Planning',
    navigationLabel: 'Response Planning',
  },
  {
    id: 'explanation-audit',
    path: '/explanation-audit',
    title: 'Explanation & Audit',
    navigationLabel: 'Explanation & Audit',
  },
]
