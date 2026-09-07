import { useCallback, useEffect, useMemo, useState } from 'react'

import { fetchDetectedEventsResponse } from '../api/detectedEvents'
import { fetchEnvironmentalData } from '../api/environmentalData'
import EnvironmentalDataModal from '../components/EnvironmentalDataModal'
import InfrastructureLayer from '../components/InfrastructureLayer'
import MapView, { type MapCoordinateClickEvent } from '../components/MapView'
import type { EnvironmentalData } from '../types/environmentalData'
import type {
  AgentPipelineStatus,
  DetectedEventsResponse,
  EventEvidence,
  IncidentDetails,
} from '../types/incidents'

import './visuals/event-detection-workspace.css'

function formatCoordinate(value: number) {
  return value.toFixed(4)
}

function formatValue(value: unknown, suffix = '') {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value}${suffix}`
    : 'Not available'
}

function contextStatus(data: EnvironmentalData | null, error: string | null) {
  if (error) return 'unavailable' as const
  if (!data) return 'unavailable' as const
  return data.metadata.collection_status === 'success' ? 'available' as const : 'partial' as const
}

function evidenceStatus(status?: string) {
  if (status === 'success') return 'available' as const
  if (status === 'partial' || status === 'partial_service_failure') return 'partial' as const
  return 'unavailable' as const
}

function EventDetectionWorkspace() {
  const [incidents, setIncidents] = useState<IncidentDetails[]>([])
  const [selectedIncident, setSelectedIncident] = useState<IncidentDetails | null>(null)
  const [incidentError, setIncidentError] = useState<string | null>(null)
  const [detectionResponse, setDetectionResponse] = useState<DetectedEventsResponse | null>(null)
  const [isLoadingIncidents, setIsLoadingIncidents] = useState(true)
  const [selectedLocation, setSelectedLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [environmentalData, setEnvironmentalData] = useState<EnvironmentalData | null>(null)
  const [environmentalError, setEnvironmentalError] = useState<string | null>(null)
  const [isLoadingContext, setIsLoadingContext] = useState(false)
  const [isPopupOpen, setIsPopupOpen] = useState(false)

  const loadContext = useCallback((latitude: number, longitude: number) => {
    setSelectedLocation({ lat: latitude, lng: longitude })
    setIsLoadingContext(true)
    setEnvironmentalError(null)
    setEnvironmentalData(null)

    void fetchEnvironmentalData(latitude, longitude)
      .then(setEnvironmentalData)
      .catch((reason: unknown) => {
        setEnvironmentalError(
          reason instanceof Error ? reason.message : 'Environmental context is unavailable',
        )
      })
      .finally(() => setIsLoadingContext(false))
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
        if (firstIncident) loadContext(firstIncident.latitude, firstIncident.longitude)
      })
      .catch((reason: unknown) => {
        if (!active) return
        setIncidentError(
          reason instanceof Error ? reason.message : 'Detected event data is unavailable',
        )
      })
      .finally(() => {
        if (active) setIsLoadingIncidents(false)
      })

    return () => {
      active = false
    }
  }, [loadContext])

  const selectIncident = (incident: IncidentDetails) => {
    setSelectedIncident(incident)
    setIsPopupOpen(false)
    loadContext(incident.latitude, incident.longitude)
  }

  const handleMapClick = (event: MapCoordinateClickEvent) => {
    const { lat, lng } = event.lngLat
    if (lat < 29.45 || lat > 33.35 || lng < 34.26 || lng > 35.90) return

    setIsPopupOpen(true)
    loadContext(lat, lng)
  }

  const evidence = useMemo<EventEvidence[]>(() => {
    const weatherSource = environmentalData?.metadata.services.weather.source || 'Weather service'
    const geographicSource = environmentalData?.metadata.services.geospatial.source || 'Geographic service'
    const weatherStatus = evidenceStatus(environmentalData?.metadata.services.weather.status)
    const geographicStatus = evidenceStatus(environmentalData?.metadata.services.geospatial.status)
    const infrastructureCount = environmentalData
      ? (environmentalData.geospatial_context.nearby_hospitals?.length ?? 0)
        + (environmentalData.geospatial_context.nearby_police_stations?.length ?? 0)
        + (environmentalData.geospatial_context.nearby_fire_stations?.length ?? 0)
      : 0
    const detectionService = detectionResponse?.metadata.services.detection

    return [
      {
        category: 'detection',
        source: detectionService?.source || 'Detected-events pipeline',
        status: evidenceStatus(detectionService?.status),
        summary: detectionService
          ? `Detection service reported: ${detectionService.status}. Raw FIRMS hotspot records are not exposed separately.`
          : 'Detection service metadata has not been returned.',
      },
      {
        category: 'environmental',
        source: weatherSource,
        status: weatherStatus,
        summary: environmentalError
          ? environmentalError
          : environmentalData
            ? `Context collected with status: ${environmentalData.metadata.services.weather.status}.`
            : 'Environmental context has not been returned.',
      },
      {
        category: 'geographic',
        source: geographicSource,
        status: geographicStatus,
        summary: environmentalError
          ? environmentalError
          : environmentalData
            ? `Context collected with status: ${environmentalData.metadata.services.geospatial.status}.`
            : 'Geographic context has not been returned.',
      },
      {
        category: 'infrastructure',
        source: 'Nearby infrastructure',
        status: geographicStatus,
        summary: environmentalData
          ? `${infrastructureCount} nearby infrastructure features returned.`
          : 'Infrastructure context has not been returned.',
      },
    ]
  }, [detectionResponse, environmentalData, environmentalError])

  const pipeline = useMemo<AgentPipelineStatus[]>(() => {
    const collectionState = isLoadingContext
      ? 'in-progress'
      : contextStatus(environmentalData, environmentalError)
    const detectionService = detectionResponse?.metadata.services.detection
    const riskService = detectionResponse?.metadata.services.risk_analysis
    const planningService = detectionResponse?.metadata.services.response_planning

    return [
      {
        name: 'Data Collection Agents',
        emphasis: 'primary',
        status: collectionState,
        detail: isLoadingContext
          ? 'Collecting environmental and geographic context for the selected location.'
          : environmentalData
            ? `Latest context request: ${environmentalData.metadata.collection_status}.`
            : 'No context response is currently available.',
      },
      {
        name: 'Shared Data Layer / PostGIS',
        emphasis: 'primary',
        status: 'unavailable',
        detail: 'Intended shared persistence layer; connection and runtime status are not exposed by this frontend contract.',
      },
      {
        name: 'Anomaly Detectors',
        emphasis: 'primary',
        status: evidenceStatus(detectionService?.status),
        detail: isLoadingIncidents
          ? 'Awaiting the detected-events pipeline response; individual stage execution is not exposed.'
          : detectionService
            ? `Observed pipeline status: ${detectionService.status}; source: ${detectionService.source || 'not reported'}.`
            : 'No detection service metadata is available.',
      },
      {
        name: 'Coordinator / Strainer',
        emphasis: 'downstream',
        status: 'unavailable',
        detail: 'Correlates, deduplicates and groups detection candidates into incidents. Correlation output and runtime status are not exposed here.',
      },
      {
        name: 'Emergency / Non-emergency Routing',
        emphasis: 'downstream',
        status: 'unavailable',
        detail: 'Intended Coordinator routing decision; no emergency classification or routing status is exposed here.',
      },
      {
        name: 'Response Planning',
        emphasis: 'downstream',
        status: evidenceStatus(planningService?.status),
        detail: planningService
          ? `Observed planning service: ${planningService.status}; source: ${planningService.source || 'not reported'}. Risk-analysis service: ${riskService?.status || 'not reported'}; source: ${riskService?.source || 'not reported'}. This does not confirm Coordinator routing.`
          : `No response-planning service metadata is available. Risk-analysis service: ${riskService?.status || 'not reported'}; source: ${riskService?.source || 'not reported'}.`,
      },
      {
        name: 'Resource Allocation / Response Implementation',
        emphasis: 'downstream',
        status: evidenceStatus(detectionResponse?.metadata.services.resource_allocation?.status),
        detail: `Resource selection status: ${detectionResponse?.metadata.services.resource_allocation?.status || 'Not provided'}. Operational dispatch is not exposed; nearby infrastructure remains context.`,
      },
    ]
  }, [detectionResponse, environmentalData, environmentalError, isLoadingContext, isLoadingIncidents])

  const detectionStatus = detectionResponse?.metadata.services.detection?.status
  const detectionFailed =
    detectionResponse?.metadata.collection_status === 'failed' || detectionStatus === 'failed'

  const currentWeather = environmentalData?.weather?.current
  const geographicContext = environmentalData?.geospatial_context

  return (
    <main className="event-workspace">
      <header className="event-workspace__header">
        <p className="event-workspace__eyebrow">Detection / anomaly assessment</p>
        <h1>Event Detection Workspace</h1>
        <p>
          Review detected event/anomaly candidates and available pipeline context.
          The Coordinator / Strainer correlates and deduplicates candidates into incidents
          before routing; this workspace does not confirm that correlation has occurred.
        </p>
      </header>

      <div className="event-workspace__notice" role="status">
        <strong>Authoritative pipeline output:</strong> detected candidates are returned only after the
        detected-events pipeline reports a positive detection. Missing analysis remains unavailable.
      </div>

      <section className="event-panel" aria-labelledby="event-overview-title">
        <div className="event-panel__heading">
          <div>
            <p className="event-panel__label">Event overview</p>
            <h2 id="event-overview-title">Selected detection candidate</h2>
          </div>
          {incidents.length > 1 && (
            <label className="event-selector">
              Detected event
              <select
                value={selectedIncident?.id ?? ''}
                onChange={(event) => {
                  const incident = incidents.find((item) => String(item.id) === event.target.value)
                  if (incident) selectIncident(incident)
                }}
              >
                {incidents.map((incident) => (
                  <option key={incident.id} value={incident.id}>{incident.title}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        {isLoadingIncidents && <p>Running event detection and assessment. This can take up to 90 seconds.</p>}
        {incidentError && <p className="event-message event-message--error">{incidentError}</p>}
        {!isLoadingIncidents && !incidentError && !selectedIncident && (
          <p className="event-message">
            {detectionFailed
              ? 'The detection provider could not complete the current scan.'
              : 'The current scan completed with no fire detection candidate returned.'}
          </p>
        )}
        {selectedIncident && (
          <div className="incident-facts">
            <div><span>Event type</span><strong>{selectedIncident.type || 'Not provided'}</strong></div>
            <div><span>Location</span><strong>{formatCoordinate(selectedIncident.latitude)}, {formatCoordinate(selectedIncident.longitude)}</strong></div>
            <div><span>Risk level</span><strong>{selectedIncident.risk_level || 'Not assessed'}</strong></div>
            <div><span>Risk score</span><strong>{formatValue(selectedIncident.risk_score, '/100')}</strong></div>
            <div><span>Detection status</span><strong>{detectionStatus || 'Not provided'}</strong></div>
            <div><span>Detection confidence</span><strong>{selectedIncident.detection_confidence || 'Not provided'}</strong></div>
            <div><span>Risk confidence</span><strong>{selectedIncident.confidence || 'Not provided'}</strong></div>
            <div><span>Analysis status</span><strong>{selectedIncident.analysis_status || 'Not provided'}</strong></div>
            <div><span>Planning status</span><strong>{selectedIncident.planning_status || 'Not provided'}</strong></div>
          </div>
        )}
      </section>

      <div className="event-workspace__columns">
        <section className="event-panel" aria-labelledby="evidence-title">
          <p className="event-panel__label">Evidence</p>
          <h2 id="evidence-title">Available source context</h2>
          <div className="evidence-list">
            {evidence.map((item) => (
              <article key={item.category} className="evidence-item">
                <div>
                  <span>{item.category}</span>
                  <h3>{item.source}</h3>
                </div>
                <span className={`event-status event-status--${item.status}`}>{item.status}</span>
                <p>{item.summary}</p>
              </article>
            ))}
          </div>
          {selectedIncident?.evidence_gaps?.length ? (
            <article className="evidence-item">
              <div><span>analysis</span><h3>Evidence gaps</h3></div>
              <span className="event-status event-status--partial">reported</span>
              <ul>{selectedIncident.evidence_gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>
            </article>
          ) : null}
          {selectedIncident?.protocol_citations?.length ? (
            <article className="evidence-item">
              <div><span>provenance</span><h3>Verified protocol citations</h3></div>
              <span className="event-status event-status--available">available</span>
              <ul>
                {selectedIncident.protocol_citations.map((citation) => (
                  <li key={citation.chunk_id}>
                    {citation.source_url ? (
                      <a href={citation.source_url} target="_blank" rel="noreferrer">{citation.document_title}</a>
                    ) : citation.document_title}
                    {citation.heading_path ? ` · ${citation.heading_path}` : ''}
                    <blockquote>“{citation.quoted_text}”</blockquote>
                  </li>
                ))}
              </ul>
            </article>
          ) : null}
        </section>

        <section className="event-panel" aria-labelledby="pipeline-title">
          <p className="event-panel__label">Intended architecture / available service metadata</p>
          <h2 id="pipeline-title">Architectural processing stages</h2>
          <ol className="pipeline-list">
            {pipeline.map((stage) => (
              <li key={stage.name} className={stage.emphasis === 'primary' ? 'pipeline-stage pipeline-stage--primary' : 'pipeline-stage'}>
                <div>
                  <h3>{stage.name}</h3>
                  <p>{stage.detail}</p>
                </div>
                <span className={`event-status event-status--${stage.status}`}>{stage.status.replace('-', ' ')}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>

      <section className="event-panel" aria-labelledby="context-title">
        <p className="event-panel__label">Selected location context</p>
        <h2 id="context-title">Environmental and geographic context</h2>
        <div className="context-summary">
          <div><span>Temperature</span><strong>{formatValue(currentWeather?.temperature_c, '°C')}</strong></div>
          <div><span>Humidity</span><strong>{formatValue(currentWeather?.humidity_percent, '%')}</strong></div>
          <div><span>Wind speed</span><strong>{formatValue(currentWeather?.wind_speed_kmh, ' km/h')}</strong></div>
          <div><span>Precipitation</span><strong>{formatValue(currentWeather?.precipitation_mm, ' mm')}</strong></div>
          <div><span>Terrain</span><strong>{String(geographicContext?.terrain_type || 'Not available')}</strong></div>
          <div><span>Region</span><strong>{String(geographicContext?.region_type || 'Not available')}</strong></div>
          <div><span>Context timestamp</span><strong>{environmentalData?.metadata.timestamp ? new Date(environmentalData.metadata.timestamp).toLocaleString() : 'Not available'}</strong></div>
        </div>
        <div className="event-workspace__map">
          <MapView
            events={incidents}
            onClick={handleMapClick}
            selectedLocation={selectedLocation}
          >
            <div className="event-map-notice">Markers reflect detected-events pipeline output</div>
            {environmentalData && (
              <InfrastructureLayer
                hospitals={environmentalData.geospatial_context.nearby_hospitals ?? []}
                policeStations={environmentalData.geospatial_context.nearby_police_stations ?? []}
                fireStations={environmentalData.geospatial_context.nearby_fire_stations ?? []}
              />
            )}
            <EnvironmentalDataModal
              isOpen={isPopupOpen}
              onClose={() => setIsPopupOpen(false)}
              latitude={selectedLocation?.lat ?? null}
              longitude={selectedLocation?.lng ?? null}
              envData={environmentalData}
              isLoading={isLoadingContext}
              error={environmentalError}
            />
          </MapView>
        </div>
      </section>
    </main>
  )
}

export default EventDetectionWorkspace
