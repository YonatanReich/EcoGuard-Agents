import { useCallback, useEffect, useMemo, useState } from 'react'

import { fetchDetectedEvents } from '../api/detectedEvents'
import { fetchEnvironmentalData } from '../api/environmentalData'
import EnvironmentalDataModal from '../components/EnvironmentalDataModal'
import InfrastructureLayer from '../components/InfrastructureLayer'
import MapView, { type MapCoordinateClickEvent } from '../components/MapView'
import type { EnvironmentalData } from '../types/environmentalData'
import type {
  AgentPipelineStatus,
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

    void fetchDetectedEvents()
      .then((events) => {
        if (!active) return
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

    return [
      {
        category: 'detection',
        source: 'Actual detection evidence',
        status: 'unavailable',
        summary: 'FIRMS and Telegram evidence are not exposed by a frontend-facing event endpoint.',
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
  }, [environmentalData, environmentalError])

  const pipeline = useMemo<AgentPipelineStatus[]>(() => {
    const collectionState = isLoadingContext
      ? 'in-progress'
      : contextStatus(environmentalData, environmentalError)

    return [
      {
        name: 'Data Collection Agent',
        emphasis: 'primary',
        status: collectionState,
        detail: isLoadingContext
          ? 'Collecting environmental and geographic context for the selected location.'
          : environmentalData
            ? `Latest context request: ${environmentalData.metadata.collection_status}.`
            : 'No context response is currently available.',
      },
      {
        name: 'Event Detection Agent',
        emphasis: 'primary',
        status: 'unavailable',
        detail: 'Runtime status and underlying detection evidence are not exposed by the current backend.',
      },
      {
        name: 'Risk Analysis Agent',
        emphasis: 'primary',
        status: selectedIncident ? 'partial' : 'unavailable',
        detail: selectedIncident
          ? 'A demonstration risk assessment is present; runtime processing status and confidence are unavailable.'
          : 'No risk assessment is available.',
      },
      {
        name: 'Resource Allocation Agent',
        emphasis: 'downstream',
        status: 'unavailable',
        detail: 'Downstream stage; not evaluated in this workspace.',
      },
      {
        name: 'Response Planning Agent',
        emphasis: 'downstream',
        status: 'unavailable',
        detail: 'Downstream stage; not evaluated in this workspace.',
      },
      {
        name: 'LLM Coordination Agent',
        emphasis: 'downstream',
        status: 'unavailable',
        detail: 'Downstream stage; no LLM runtime or audit data is exposed here.',
      },
    ]
  }, [environmentalData, environmentalError, isLoadingContext, selectedIncident])

  const currentWeather = environmentalData?.weather?.current
  const geographicContext = environmentalData?.geospatial_context

  return (
    <main className="event-workspace">
      <header className="event-workspace__header">
        <p className="event-workspace__eyebrow">Incident assessment</p>
        <h1>Event Detection Workspace</h1>
        <p>
          Review an incident record, its available context, and the processing information
          exposed by the current EcoGuard pipeline before moving to downstream planning.
        </p>
      </header>

      <div className="event-workspace__notice" role="status">
        <strong>Demonstration event record:</strong> `/api/detected-events` currently returns
        hard-coded data. It is not a verified live operational detection.
      </div>

      <section className="event-panel" aria-labelledby="event-overview-title">
        <div className="event-panel__heading">
          <div>
            <p className="event-panel__label">Event overview</p>
            <h2 id="event-overview-title">Selected incident</h2>
          </div>
          {incidents.length > 1 && (
            <label className="event-selector">
              Incident
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

        {isLoadingIncidents && <p>Loading the current event record…</p>}
        {incidentError && <p className="event-message event-message--error">{incidentError}</p>}
        {!isLoadingIncidents && !incidentError && !selectedIncident && (
          <p className="event-message">No event record is currently available.</p>
        )}
        {selectedIncident && (
          <div className="incident-facts">
            <div><span>Event type</span><strong>{selectedIncident.type || 'Not provided'}</strong></div>
            <div><span>Location</span><strong>{formatCoordinate(selectedIncident.latitude)}, {formatCoordinate(selectedIncident.longitude)}</strong></div>
            <div><span>Risk level</span><strong>{selectedIncident.risk_level || 'Not provided'} <small>demo assessment</small></strong></div>
            <div><span>Risk score</span><strong>{formatValue(selectedIncident.risk_score, '/100')} <small>demo assessment</small></strong></div>
            <div><span>Detection status</span><strong>Not operationally verified</strong></div>
            <div><span>Confidence</span><strong>Not provided by backend</strong></div>
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
        </section>

        <section className="event-panel" aria-labelledby="pipeline-title">
          <p className="event-panel__label">Agent pipeline status</p>
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
            <div className="event-map-notice">Event markers are demonstration records</div>
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
