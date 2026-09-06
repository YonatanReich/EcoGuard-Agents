import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'

import { fetchDetectedEvents } from '../api/detectedEvents'
import { fetchEnvironmentalData } from '../api/environmentalData'
import InfrastructureLayer, { type InfrastructureItem } from '../components/InfrastructureLayer'
import MapView from '../components/MapView'
import type { EnvironmentalData } from '../types/environmentalData'
import type { IncidentDetails } from '../types/incidents'
import type { AllocatedResponseResource } from '../types/responseResources'
import { straightLineDistanceKm } from '../utils/geospatial'

import './visuals/response-planning.css'

type ResponseInfrastructure = InfrastructureItem & {
  category: 'Fire station' | 'Police station' | 'Hospital'
  distanceKm: number
}

type VisualizationMode = '2d' | '3d'

const Incident3DView = lazy(() => import('../components/Incident3DView'))
const NO_ALLOCATED_RESOURCES: readonly AllocatedResponseResource[] = Object.freeze([])
const DEFAULT_VISUALIZATION_HEIGHT = 520
const MIN_VISUALIZATION_HEIGHT = 420
const MAX_VISUALIZATION_HEIGHT = 900
const VISUALIZATION_HEIGHT_KEY = 'ecoguard-response-visualization-height'

function displayName(value: string) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function ResponsePlanning() {
  const [incidents, setIncidents] = useState<IncidentDetails[]>([])
  const [selectedIncident, setSelectedIncident] = useState<IncidentDetails | null>(null)
  const [incidentError, setIncidentError] = useState<string | null>(null)
  const [isLoadingIncident, setIsLoadingIncident] = useState(true)
  const [environmentalData, setEnvironmentalData] = useState<EnvironmentalData | null>(null)
  const [environmentalError, setEnvironmentalError] = useState<string | null>(null)
  const [isLoadingContext, setIsLoadingContext] = useState(false)
  const [visualizationMode, setVisualizationMode] = useState<VisualizationMode>('2d')
  const [visualizationHeight, setVisualizationHeight] = useState(() => {
    const storedHeight = Number(sessionStorage.getItem(VISUALIZATION_HEIGHT_KEY))
    return Number.isFinite(storedHeight)
      ? Math.min(MAX_VISUALIZATION_HEIGHT, Math.max(MIN_VISUALIZATION_HEIGHT, storedHeight))
      : DEFAULT_VISUALIZATION_HEIGHT
  })
  const [isVisualizationExpanded, setIsVisualizationExpanded] = useState(false)
  const restoredVisualizationHeightRef = useRef(DEFAULT_VISUALIZATION_HEIGHT)
  const twoDimensionalTabRef = useRef<HTMLButtonElement>(null)
  const threeDimensionalTabRef = useRef<HTMLButtonElement>(null)

  const loadContext = useCallback((incident: IncidentDetails) => {
    setIsLoadingContext(true)
    setEnvironmentalError(null)
    setEnvironmentalData(null)

    void fetchEnvironmentalData(incident.latitude, incident.longitude)
      .then(setEnvironmentalData)
      .catch((reason: unknown) => {
        setEnvironmentalError(
          reason instanceof Error ? reason.message : 'Response context is unavailable',
        )
      })
      .finally(() => setIsLoadingContext(false))
  }, [])

  useEffect(() => {
    let active = true

    void fetchDetectedEvents()
      .then((events) => {
        if (!active) return
        setIncidents(events)
        const firstIncident = events[0] ?? null
        setSelectedIncident(firstIncident)
        if (firstIncident) loadContext(firstIncident)
      })
      .catch((reason: unknown) => {
        if (!active) return
        setIncidentError(
          reason instanceof Error ? reason.message : 'Incident data is unavailable',
        )
      })
      .finally(() => {
        if (active) setIsLoadingIncident(false)
      })

    return () => {
      active = false
    }
  }, [loadContext])

  const selectIncident = (incident: IncidentDetails) => {
    setSelectedIncident(incident)
    loadContext(incident)
  }

  const provisionalActions = useMemo(() => {
    if (!selectedIncident?.response_plan) return []
    return Array.isArray(selectedIncident.response_plan)
      ? selectedIncident.response_plan
      : [selectedIncident.response_plan]
  }, [selectedIncident])

  const nearbyInfrastructure = useMemo<ResponseInfrastructure[]>(() => {
    if (!selectedIncident || !environmentalData) return []

    const origin = {
      latitude: selectedIncident.latitude,
      longitude: selectedIncident.longitude,
    }
    const withCategory = (
      items: InfrastructureItem[],
      category: ResponseInfrastructure['category'],
    ) => items
      .filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude))
      .map((item) => ({
        ...item,
        category,
        distanceKm: straightLineDistanceKm(origin, item),
      }))

    return [
      ...withCategory(environmentalData.geospatial_context.nearby_fire_stations ?? [], 'Fire station'),
      ...withCategory(environmentalData.geospatial_context.nearby_police_stations ?? [], 'Police station'),
      ...withCategory(environmentalData.geospatial_context.nearby_hospitals ?? [], 'Hospital'),
    ].sort((left, right) => left.distanceKm - right.distanceKm)
  }, [environmentalData, selectedIncident])

  const nearbyRoads = environmentalData?.geospatial_context.nearby_roads ?? []
  const geospatialStatus = environmentalData?.metadata.services.geospatial.status
  const missingGeospatialLayers = environmentalData?.missing_layers ?? []
  const hasPartialGeospatialContext = Boolean(
    environmentalData &&
    (geospatialStatus !== 'success' || missingGeospatialLayers.length > 0),
  )

  const selectVisualization = (mode: VisualizationMode, moveFocus = false) => {
    setVisualizationMode(mode)
    if (moveFocus) {
      const tab = mode === '2d' ? twoDimensionalTabRef.current : threeDimensionalTabRef.current
      tab?.focus()
    }
  }

  const handleVisualizationKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    selectVisualization(visualizationMode === '2d' ? '3d' : '2d', true)
  }

  const updateVisualizationHeight = useCallback((height: number) => {
    const nextHeight = Math.min(MAX_VISUALIZATION_HEIGHT, Math.max(MIN_VISUALIZATION_HEIGHT, height))
    setVisualizationHeight(nextHeight)
    sessionStorage.setItem(VISUALIZATION_HEIGHT_KEY, String(Math.round(nextHeight)))
    window.requestAnimationFrame(() => window.dispatchEvent(new Event('resize')))
  }, [])

  const startVisualizationResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const startY = event.clientY
    const startHeight = visualizationHeight
    setIsVisualizationExpanded(false)
    event.currentTarget.setPointerCapture(event.pointerId)

    const resize = (pointerEvent: PointerEvent) => {
      updateVisualizationHeight(startHeight + pointerEvent.clientY - startY)
    }
    const finish = () => {
      window.removeEventListener('pointermove', resize)
      window.removeEventListener('pointerup', finish)
    }
    window.addEventListener('pointermove', resize)
    window.addEventListener('pointerup', finish)
  }

  const toggleVisualizationExpansion = () => {
    if (isVisualizationExpanded) {
      updateVisualizationHeight(restoredVisualizationHeightRef.current)
      setIsVisualizationExpanded(false)
      return
    }
    restoredVisualizationHeightRef.current = visualizationHeight
    updateVisualizationHeight(Math.min(MAX_VISUALIZATION_HEIGHT, window.innerHeight * 0.82))
    setIsVisualizationExpanded(true)
  }

  return (
    <main className="response-workspace">
      <header className="response-workspace__header">
        <p className="response-workspace__eyebrow">Operational coordination</p>
        <h1>Response Planning</h1>
        <p>
          Review provisional response suggestions alongside real geographic and nearby
          infrastructure context. This workspace does not dispatch or allocate resources.
        </p>
      </header>

      <div className="response-workspace__warning" role="status">
        <strong>Demonstration planning data:</strong> the current incident recommendations and
        actions are stub fields, not verified live instructions or assignments.
      </div>

      <section className="response-panel" aria-labelledby="response-incident-title">
        <div className="response-panel__heading">
          <div>
            <p className="response-panel__label">Incident summary</p>
            <h2 id="response-incident-title">Planning context</h2>
          </div>
          {incidents.length > 1 && (
            <label className="response-selector">
              Incident
              <select
                value={selectedIncident?.id ?? ''}
                onChange={(event) => {
                  const incident = incidents.find((item) => String(item.id) === event.target.value)
                  if (incident) selectIncident(incident)
                }}
              >
                {incidents.map((incident) => (
                  <option value={incident.id} key={incident.id}>{incident.title}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        {isLoadingIncident && <p className="response-message">Loading incident context…</p>}
        {incidentError && <p className="response-message response-message--error">{incidentError}</p>}
        {!isLoadingIncident && !incidentError && !selectedIncident && (
          <p className="response-message">No incident is available for planning.</p>
        )}
        {selectedIncident && (
          <div className="response-facts">
            <div><span>Event type</span><strong>{selectedIncident.type || 'Not provided'}</strong></div>
            <div><span>Location</span><strong>{selectedIncident.latitude.toFixed(4)}, {selectedIncident.longitude.toFixed(4)}</strong></div>
            <div><span>Risk / priority context</span><strong>{selectedIncident.risk_level || 'Not provided'} <small>demo assessment</small></strong></div>
            <div><span>Operational status</span><strong>Not verified</strong></div>
            <div><span>Response timeline</span><strong>Not available</strong></div>
            <div><span>Dispatch state</span><strong>Not available</strong></div>
          </div>
        )}
      </section>

      <div className="response-workspace__columns">
        <section className="response-panel" aria-labelledby="recommended-units-title">
          <p className="response-panel__label">Recommended authorities / units</p>
          <h2 id="recommended-units-title">Provisional suggestions</h2>
          <p className="response-panel__note">
            These values come from the demonstration incident response. Availability, capacity,
            assignment, and authority confirmation are not exposed.
          </p>
          {selectedIncident?.recommended_units?.length ? (
            <ul className="recommended-unit-list">
              {selectedIncident.recommended_units.map((unit) => (
                <li key={unit}>
                  <strong>{displayName(unit)}</strong>
                  <span>Suggested · demonstration only</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="response-message">No recommended authorities or units are available.</p>
          )}
        </section>

        <section className="response-panel" aria-labelledby="action-plan-title">
          <p className="response-panel__label">Action plan</p>
          <h2 id="action-plan-title">Provisional actions</h2>
          {provisionalActions.length ? (
            <ol className="response-action-list">
              {provisionalActions.map((action, index) => (
                <li key={`${index}-${action}`}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{action}</strong>
                    <small>Demonstration action—not a live operational instruction</small>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="response-message">No response-plan actions are available.</p>
          )}
        </section>
      </div>

      <section className="response-panel" aria-labelledby="infrastructure-title">
        <p className="response-panel__label">Nearby response infrastructure</p>
        <h2 id="infrastructure-title">Geographic resource context</h2>
        <p className="response-panel__note">
          Nearby facilities are geographic context only. They are not confirmed available,
          assigned, staffed, or dispatched. Distances are straight-line estimates, not routes.
        </p>
        <div className="response-context-status" role="status">
          <div>
            <span>Geospatial service</span>
            <strong>{geospatialStatus || (isLoadingContext ? 'Loading' : 'Not available')}</strong>
          </div>
          <button
            type="button"
            disabled={!selectedIncident || isLoadingContext}
            onClick={() => {
              if (selectedIncident) loadContext(selectedIncident)
            }}
          >
            {isLoadingContext ? 'Loading context…' : 'Retry environmental context'}
          </button>
        </div>
        {hasPartialGeospatialContext && (
          <div className="response-context-status__partial">
            <strong>Partial geospatial response</strong>
            {missingGeospatialLayers.length > 0 ? (
              <span>Missing layers: {missingGeospatialLayers.map(displayName).join(', ')}.</span>
            ) : (
              <span>The geospatial provider did not report all layers as available.</span>
            )}
          </div>
        )}
        {isLoadingContext && <p className="response-message">Loading real geographic context…</p>}
        {environmentalError && <p className="response-message response-message--error">{environmentalError}</p>}
        {!isLoadingContext && !environmentalError && nearbyInfrastructure.length === 0 && (
          <p className="response-message">No nearby emergency infrastructure was returned.</p>
        )}
        <div className="response-infrastructure-list">
          {nearbyInfrastructure.map((item) => (
            <article key={`${item.category}-${item.osm_id ?? item.name}`}>
              <div>
                <span>{item.category}</span>
                <h3>{item.name || 'Unnamed facility'}</h3>
              </div>
              <dl>
                <div><dt>Straight-line distance</dt><dd>{item.distanceKm.toFixed(2)} km</dd></div>
                <div><dt>Coordinates</dt><dd>{item.latitude.toFixed(4)}, {item.longitude.toFixed(4)}</dd></div>
                <div><dt>Operational availability</dt><dd>Not available</dd></div>
              </dl>
            </article>
          ))}
        </div>

        <div className="access-context">
          <h3>Road and access context</h3>
          <p>No travel time, route condition, or access clearance is provided by the backend.</p>
          {nearbyRoads.length > 0 ? (
            <ul>
              {nearbyRoads.slice(0, 8).map((road, index) => {
                const hasCoordinates = typeof road.latitude === 'number' && typeof road.longitude === 'number'
                const distance = hasCoordinates && selectedIncident
                  ? straightLineDistanceKm(
                    { latitude: selectedIncident.latitude, longitude: selectedIncident.longitude },
                    { latitude: road.latitude as number, longitude: road.longitude as number },
                  )
                  : null

                return (
                  <li key={`${road.ref || road.name || road.type}-${index}`}>
                    <strong>{road.name || road.ref || 'Unnamed road'}</strong>
                    <span>{displayName(road.type)}{distance !== null ? ` · ${distance.toFixed(2)} km straight-line` : ''}</span>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="response-message">No nearby road context was returned.</p>
          )}
        </div>

        {selectedIncident && (
          <div
            className="response-visualization"
            style={{ '--response-visualization-height': `${visualizationHeight}px` } as CSSProperties}
          >
            <div className="response-view-toolbar">
            <div className="response-view-tabs" role="tablist" aria-label="Incident map view">
              <button
                ref={twoDimensionalTabRef}
                id="response-view-tab-2d"
                type="button"
                role="tab"
                aria-selected={visualizationMode === '2d'}
                aria-controls="response-view-panel-2d"
                tabIndex={visualizationMode === '2d' ? 0 : -1}
                onClick={() => selectVisualization('2d')}
                onKeyDown={handleVisualizationKeyDown}
              >
                2D Map View
              </button>
              <button
                ref={threeDimensionalTabRef}
                id="response-view-tab-3d"
                type="button"
                role="tab"
                aria-selected={visualizationMode === '3d'}
                aria-controls="response-view-panel-3d"
                tabIndex={visualizationMode === '3d' ? 0 : -1}
                onClick={() => selectVisualization('3d')}
                onKeyDown={handleVisualizationKeyDown}
              >
                3D Operational View
              </button>
            </div>
              <button
                className="response-view-expand"
                type="button"
                aria-expanded={isVisualizationExpanded}
                onClick={toggleVisualizationExpansion}
              >
                {isVisualizationExpanded ? 'Restore view' : 'Expand view'}
              </button>
            </div>

            {visualizationMode === '2d' && (
              <div
                id="response-view-panel-2d"
                className="response-map"
                role="tabpanel"
                aria-labelledby="response-view-tab-2d"
              >
                <MapView
                  events={[selectedIncident]}
                  selectedLocation={{ lat: selectedIncident.latitude, lng: selectedIncident.longitude }}
                >
                  {environmentalData && (
                    <InfrastructureLayer
                      hospitals={environmentalData.geospatial_context.nearby_hospitals ?? []}
                      policeStations={environmentalData.geospatial_context.nearby_police_stations ?? []}
                      fireStations={environmentalData.geospatial_context.nearby_fire_stations ?? []}
                    />
                  )}
              <div className="response-map__notice">Demo incident · nearby infrastructure is not allocated</div>
                </MapView>
              </div>
            )}

            {visualizationMode === '3d' && (
              <div
                id="response-view-panel-3d"
                className="response-map response-map--3d"
                role="tabpanel"
                aria-labelledby="response-view-tab-3d"
              >
                <Suspense fallback={<div className="response-3d-loading" role="status">Loading 3D viewer…</div>}>
                  <Incident3DView
                    incident={selectedIncident}
                    context={environmentalData?.geospatial_context ?? null}
                    allocatedResources={NO_ALLOCATED_RESOURCES}
                    riskArea={null}
                  />
                </Suspense>
              </div>
            )}
            <div
              className="response-view-resize-handle"
              role="separator"
              aria-label="Resize operational visualization"
              aria-orientation="horizontal"
              aria-valuemin={MIN_VISUALIZATION_HEIGHT}
              aria-valuemax={MAX_VISUALIZATION_HEIGHT}
              aria-valuenow={Math.round(visualizationHeight)}
              tabIndex={0}
              onPointerDown={startVisualizationResize}
              onKeyDown={(event) => {
                if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
                event.preventDefault()
                setIsVisualizationExpanded(false)
                updateVisualizationHeight(
                  visualizationHeight + (event.key === 'ArrowDown' ? 40 : -40),
                )
              }}
            >
              <span>Drag to resize</span>
            </div>
          </div>
        )}
      </section>

      <section className="response-panel response-agent-context" aria-labelledby="planning-status-title">
        <div>
          <p className="response-panel__label">Planning system status</p>
          <h2 id="planning-status-title">Relevant architectural stages</h2>
        </div>
        <div><strong>Resource Allocation Agent</strong><span>Runtime status not exposed</span></div>
        <div><strong>Response Planning Agent</strong><span>Runtime status not exposed</span></div>
      </section>

      <nav className="response-workflow" aria-label="Response workflow">
        <Link to="/event-detection">← Back to Event Detection</Link>
        <Link to="/explanation-audit">Continue to Explanation &amp; Audit →</Link>
      </nav>
    </main>
  )
}

export default ResponsePlanning
