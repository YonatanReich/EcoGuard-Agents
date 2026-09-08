import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'

import { fetchDetectedEventsResponse } from '../api/detectedEvents'
import { fetchEnvironmentalData } from '../api/environmentalData'
import AirPollutionContextLayer, { PROXIMITY_LIMITATION } from '../components/AirPollutionContextLayer'
import InfrastructureLayer, { type InfrastructureItem } from '../components/InfrastructureLayer'
import MapView from '../components/MapView'
import type { EnvironmentalData } from '../types/environmentalData'
import type { DetectedEventsResponse, IncidentDetails } from '../types/incidents'
import { selectedFacilitySimulation } from '../utils/selectedFacilitySimulation'
import { straightLineDistanceKm } from '../utils/geospatial'
import {
  eventBySelectionKey,
  eventSelectionKey,
  isAirPollutionEvent,
  primaryPollutionObservation,
} from '../utils/airPollutionEvents'

import './visuals/response-planning.css'

type ResponseInfrastructure = InfrastructureItem & {
  category: 'Fire station' | 'Police station' | 'Hospital'
  distanceKm: number
}

type VisualizationMode = '2d' | '3d'

const Incident3DView = lazy(() => import('../components/Incident3DView'))
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
  const [detectionResponse, setDetectionResponse] = useState<DetectedEventsResponse | null>(null)
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
  const contextRequestIdRef = useRef(0)
  const selectedIsPollution = isAirPollutionEvent(selectedIncident)
  const pollutionPlan = selectedIncident?.pollution_response_plan
  const pollutionObservation = primaryPollutionObservation(selectedIncident)
  const selectedFacilityResources = useMemo(
    () => selectedIsPollution
      ? []
      : selectedFacilitySimulation(selectedIncident?.allocated_resources),
    [selectedIncident, selectedIsPollution],
  )
  const allocationStatus = selectedIncident?.allocated_resources?.status
    ?? detectionResponse?.metadata.services.resource_allocation?.status
    ?? 'Not provided'

  const loadContext = useCallback((incident: IncidentDetails) => {
    const requestId = ++contextRequestIdRef.current
    setIsLoadingContext(true)
    setEnvironmentalError(null)
    setEnvironmentalData(null)

    void fetchEnvironmentalData(incident.latitude, incident.longitude)
      .then((data) => {
        if (contextRequestIdRef.current === requestId) setEnvironmentalData(data)
      })
      .catch((reason: unknown) => {
        if (contextRequestIdRef.current !== requestId) return
        setEnvironmentalError(
          reason instanceof Error ? reason.message : 'Response context is unavailable',
        )
      })
      .finally(() => {
        if (contextRequestIdRef.current === requestId) setIsLoadingContext(false)
      })
  }, [])

  useEffect(() => {
    let active = true

    void fetchDetectedEventsResponse()
      .then((response) => {
        if (!active) return
        const events = response.events
        setDetectionResponse(response)
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
    if (isAirPollutionEvent(incident)) setVisualizationMode('2d')
    loadContext(incident)
  }

  const planningActions = useMemo(() => {
    if (selectedIsPollution) {
      return pollutionPlan?.actions?.map((action) => action.recommendation) ?? []
    }
    if (selectedIncident?.response_actions?.length) {
      return selectedIncident.response_actions.map((action) => action.action)
    }
    if (!selectedIncident?.response_plan) return []
    return Array.isArray(selectedIncident.response_plan)
      ? selectedIncident.response_plan
      : [selectedIncident.response_plan]
  }, [pollutionPlan, selectedIncident, selectedIsPollution])

  const recommendedTypes = selectedIsPollution
    ? Array.from(new Set([
      ...(pollutionPlan?.recommended_authority_types ?? []),
      ...(pollutionPlan?.recommended_resource_types ?? []),
    ]))
    : selectedIncident?.recommended_units ?? []

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
  const suppliedSpatialContext = selectedIsPollution ? selectedIncident?.spatial_context : null
  const missingGeospatialLayers = environmentalData?.missing_layers ?? []
  const hasPartialGeospatialContext = Boolean(
    environmentalData &&
    (geospatialStatus !== 'success' || missingGeospatialLayers.length > 0),
  )
  const detectionStatus = detectionResponse?.metadata.services.detection?.status
  const detectionFailed =
    detectionResponse?.metadata.collection_status === 'failed' || detectionStatus === 'failed'
  const geospatialStatusLabel = selectedIncident
    ? geospatialStatus || (isLoadingContext ? 'Loading' : 'Not available')
    : isLoadingIncident
      ? 'Waiting for detection scan'
      : incidentError
        ? 'Not requested — detection request failed'
        : detectionFailed
          ? 'Not requested — detection failed'
          : 'Not requested — no detected event'
  const hasGroundedPlanningOutput = selectedIsPollution
    ? pollutionPlan?.status === 'success'
    : selectedIncident?.planning_status === 'success'
  const hasCompletedContextRequest = Boolean(
    selectedIncident && environmentalData && !isLoadingContext && !environmentalError,
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
    if (selectedIsPollution) return
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
        <strong>Decision-support planning:</strong> recommendations are shown only when returned
        by the current pipeline. They are not verified dispatch instructions or assignments.
        In the intended architecture, Coordinator correlation and emergency/non-emergency routing
        precede planning; allocation follows emergency planning. Those routing results are not exposed here.
      </div>

      <section className="response-panel" aria-labelledby="response-incident-title">
        <div className="response-panel__heading">
          <div>
            <p className="response-panel__label">Detected event summary</p>
            <h2 id="response-incident-title">Planning context</h2>
          </div>
          {incidents.length > 1 && (
            <label className="response-selector">
              Detected event
              <select
                value={selectedIncident ? eventSelectionKey(selectedIncident) : ''}
                onChange={(event) => {
                  const incident = eventBySelectionKey(incidents, event.target.value)
                  if (incident) selectIncident(incident)
                }}
              >
                {incidents.map((incident) => (
                  <option value={eventSelectionKey(incident)} key={eventSelectionKey(incident)}>{incident.title}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        {isLoadingIncident && (
          <p className="response-message">
            Awaiting event detection, risk analysis, and response planning output. This can take up to 90 seconds.
          </p>
        )}
        {incidentError && <p className="response-message response-message--error">{incidentError}</p>}
        {!isLoadingIncident && !incidentError && !selectedIncident && (
          <p className="response-message">
            {detectionFailed
              ? 'The detection service could not complete the current scan; no detected-event context is available.'
              : 'The current detection scan found no event available for response planning.'}
          </p>
        )}
        {selectedIncident && (
          <div className="response-facts">
            <div><span>Event type</span><strong>{selectedIsPollution ? 'Air Pollution' : selectedIncident.type || 'Not provided'}</strong></div>
            <div><span>Location</span><strong>{selectedIncident.latitude.toFixed(4)}, {selectedIncident.longitude.toFixed(4)}</strong></div>
            {selectedIsPollution && pollutionObservation && <div><span>Pollutant observation</span><strong>{pollutionObservation.pollutant} · {pollutionObservation.value} {pollutionObservation.unit}</strong></div>}
            <div><span>{selectedIsPollution ? 'Anomaly severity' : 'Risk / priority context'}</span><strong>{selectedIsPollution ? selectedIncident.anomaly?.severity ?? 'Not provided' : selectedIncident.risk_level || 'Not assessed'}</strong></div>
            {!selectedIsPollution && <div><span>Analysis status</span><strong>{selectedIncident.analysis_status || 'Not provided'}</strong></div>}
            <div><span>Planning status</span><strong>{selectedIsPollution ? pollutionPlan?.status ?? 'Not provided' : selectedIncident.planning_status || 'Not provided'}</strong></div>
            <div><span>Operational status</span><strong>Decision support · not dispatched</strong></div>
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
            These values come from the detected-event planning response. Availability, capacity,
            assignment, and authority confirmation are not exposed by the current backend.
          </p>
          {recommendedTypes.length ? (
            <ul className="recommended-unit-list">
              {recommendedTypes.map((unit) => (
                <li key={unit}>
                  <strong>{displayName(unit)}</strong>
                  <span>{selectedIsPollution ? 'Recommended type · availability and dispatch not represented' : 'Suggested · not verified or dispatched'}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="response-message">No recommended authorities or units are available.</p>
          )}
        </section>

        <section className="response-panel" aria-labelledby="action-plan-title">
          <p className="response-panel__label">Action plan</p>
          <h2 id="action-plan-title">Planning actions</h2>
          {planningActions.length ? (
            <ol className="response-action-list">
              {planningActions.map((action, index) => (
                <li key={`${index}-${action}`}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{action}</strong>
                    <small>
                      {hasGroundedPlanningOutput
                        ? 'Grounded pipeline output—not a dispatch instruction'
                        : 'Provisional data—not a live operational instruction'}
                    </small>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="response-message">No response-plan actions are available.</p>
          )}
        </section>
      </div>

      {!selectedIsPollution && <section className="response-panel" aria-labelledby="selected-facilities-title">
        <p className="response-panel__label">Resource Allocation selection</p>
        <h2 id="selected-facilities-title">Selected response facilities</h2>
        <p className="response-panel__note">
          Selection status: {allocationStatus}. EcoGuard-selected response sources; vehicle availability
          and operational dispatch are not exposed. Starting the 3D demo creates one simulated vehicle per listed facility.
        </p>
        {selectedFacilityResources.length ? (
          <ul className="recommended-unit-list">
            {selectedFacilityResources.map((resource) => (
              <li key={resource.id}>
                <strong>{resource.sourceName}</strong>
                <span>{resource.displayName} simulation source · NOT DISPATCHED</span>
              </li>
            ))}
          </ul>
        ) : <p className="response-message">No usable selected response facilities are available.</p>}
      </section>}

      {selectedIsPollution && pollutionPlan && (
        <section className="response-panel" aria-labelledby="pollution-plan-details-title">
          <p className="response-panel__label">Grounded pollution decision support</p>
          <h2 id="pollution-plan-details-title">Limitations, gaps and verified references</h2>
          {pollutionPlan.actions?.length ? (
            <div className="response-infrastructure-list">
              {pollutionPlan.actions.map((action) => (
                <article key={`${action.resource_type}-${action.recommendation}`}>
                  <div><span>{displayName(action.resource_type)}</span><h3>{action.recommendation}</h3></div>
                  <dl>
                    <div><dt>Responsible type</dt><dd>{displayName(action.responsible_authority_type)}</dd></div>
                    <div><dt>Priority</dt><dd>{displayName(action.priority)}</dd></div>
                    <div><dt>Timeframe</dt><dd>{displayName(action.timeframe)}</dd></div>
                  </dl>
                </article>
              ))}
            </div>
          ) : <p className="response-message">No grounded pollution actions are available.</p>}
          {[...(pollutionPlan.assumptions ?? []), ...(pollutionPlan.evidence_gaps ?? []), ...(pollutionPlan.limitations ?? [])].length > 0 && (
            <ul className="recommended-unit-list">
              {[...(pollutionPlan.assumptions ?? []), ...(pollutionPlan.evidence_gaps ?? []), ...(pollutionPlan.limitations ?? [])].map((item) => <li key={item}>{item}</li>)}
            </ul>
          )}
          {pollutionPlan.protocol_references?.length ? (
            <ul className="recommended-unit-list">
              {pollutionPlan.protocol_references.map((reference) => (
                <li key={reference.chunk_id}>
                  <a href={reference.source_url} target="_blank" rel="noreferrer">{reference.document_title}</a>
                  <span>Verified · {reference.heading_path}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      )}

      <section className="response-panel" aria-labelledby="infrastructure-title">
        <p className="response-panel__label">Nearby response infrastructure</p>
        <h2 id="infrastructure-title">Geographic resource context</h2>
        <p className="response-panel__note">
          Nearby facilities are geographic context only. They are not confirmed available,
          assigned, staffed, or dispatched. Distances are straight-line estimates, not routes.
        </p>
        <div className="response-context-status" role="status">
          <div>
            <span>Live supplemental geospatial lookup</span>
            <strong>{geospatialStatusLabel}</strong>
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
        {suppliedSpatialContext && (
          <div className="response-context-status" role="status">
            <div>
              <span>Event-supplied spatial context</span>
              <strong>{suppliedSpatialContext.status}</strong>
            </div>
            <small>{suppliedSpatialContext.source || 'Source not supplied'} · proximity does not confirm exposure</small>
          </div>
        )}
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
        {environmentalError && <p className="response-message response-message--error">Live supplemental context failed: {environmentalError}</p>}
        {hasCompletedContextRequest && nearbyInfrastructure.length === 0 && (
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
          ) : hasCompletedContextRequest ? (
            <p className="response-message">No nearby road context was returned.</p>
          ) : null}
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
              {!selectedIsPollution && <button
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
              </button>}
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
                  onEventSelect={selectIncident}
                  activeEvent={selectedIncident}
                  selectedLocation={{ lat: selectedIncident.latitude, lng: selectedIncident.longitude }}
                >
                  {environmentalData && (
                    <InfrastructureLayer
                      hospitals={environmentalData.geospatial_context.nearby_hospitals ?? []}
                      policeStations={environmentalData.geospatial_context.nearby_police_stations ?? []}
                      fireStations={environmentalData.geospatial_context.nearby_fire_stations ?? []}
                    />
                  )}
                  <AirPollutionContextLayer event={selectedIncident} />
                  {selectedIsPollution && selectedIncident.spatial_context && (
                    <div className="response-map__context-note">Nearby settlement points only. {PROXIMITY_LIMITATION}</div>
                  )}
              <div className="response-map__notice">Detected event / anomaly candidate · exposure and correlation are not confirmed</div>
                </MapView>
              </div>
            )}

            {!selectedIsPollution && visualizationMode === '3d' && (
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
                    selectedFacilityResources={selectedFacilityResources}
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
        <div><strong>Coordinator / Strainer</strong><span>Correlation and runtime status not exposed</span></div>
        <div><strong>Emergency / Non-emergency Routing</strong><span>Routing decision not exposed</span></div>
        <div><strong>Response Planning</strong><span>Pipeline planning status: {selectedIncident?.planning_status || 'Not provided'}</span></div>
        <div><strong>Resource Allocation / Response Implementation</strong><span>{selectedIsPollution ? 'No pollution allocation or operational implementation output is exposed.' : `Resource selection status: ${allocationStatus}. Operational dispatch not exposed. Nearby infrastructure remains geographic context.`}</span></div>
      </section>

      <nav className="response-workflow" aria-label="Response workflow">
        <Link to="/event-detection">← Back to Event Detection</Link>
        <Link to="/explanation-audit">Continue to Explanation &amp; Audit →</Link>
      </nav>
    </main>
  )
}

export default ResponsePlanning
