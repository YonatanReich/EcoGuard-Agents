import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchDetectedEventsResponse } from '../api/detectedEvents'
import { fetchEnvironmentalData } from '../api/environmentalData'
import { fetchCurrentRiskAssessment } from '../api/fireRisk'
import { useNationalRiskScan } from '../hooks/useNationalRiskScan'
import type { EnvironmentalData } from '../types/environmentalData'
import type { DetectedEventsResponse, IncidentDetails } from '../types/incidents'
import type { FireRiskAssessment } from '../types/riskAnalysis'
import {
  eventBySelectionKey,
  eventSelectionKey,
  formatEventTimestamp,
  isAirPollutionEvent,
  pollutionStationLabel,
  primaryPollutionObservation,
} from '../utils/airPollutionEvents'

import './visuals/explanation-audit.css'

type TraceState = 'available' | 'partial' | 'unavailable' | 'not-used'

type DataSourceTrace = {
  source: string
  role: string
  state: TraceState
  status: string
  timestamp?: string | null
}

const AGENT_ROLES = [
  'Data Collection Agents',
  'Shared Data Layer / PostGIS',
  'Anomaly Detectors',
  'Coordinator / Strainer',
  'Emergency / Non-emergency Routing',
  'Response Planning',
  'Resource Allocation / Response Implementation',
] as const

function formatTimestamp(value?: string | null) {
  if (!value) return 'Not available'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'Not available' : parsed.toLocaleString()
}

function displayTraceValue(value: string) {
  return value.replace(/_/g, ' ')
}

function sourceState(status?: string): TraceState {
  if (status === 'success') return 'available'
  if (status === 'partial' || status === 'partial_service_failure') return 'partial'
  return 'unavailable'
}

function ExplanationAudit() {
  const [incidents, setIncidents] = useState<IncidentDetails[]>([])
  const [selectedIncident, setSelectedIncident] = useState<IncidentDetails | null>(null)
  const [incidentError, setIncidentError] = useState<string | null>(null)
  const [detectionResponse, setDetectionResponse] = useState<DetectedEventsResponse | null>(null)
  const [isLoadingIncident, setIsLoadingIncident] = useState(true)
  const [environmentalData, setEnvironmentalData] = useState<EnvironmentalData | null>(null)
  const [environmentalError, setEnvironmentalError] = useState<string | null>(null)
  const [riskAssessment, setRiskAssessment] = useState<FireRiskAssessment | null>(null)
  const [riskError, setRiskError] = useState<string | null>(null)
  const [isLoadingTrace, setIsLoadingTrace] = useState(false)
  const traceRequestIdRef = useRef(0)
  const { scan: nationalRiskScan, error: nationalRiskError } = useNationalRiskScan()
  const selectedIsPollution = isAirPollutionEvent(selectedIncident)
  const pollutionPlan = selectedIncident?.pollution_response_plan
  const pollutionObservation = primaryPollutionObservation(selectedIncident)
  const pollutionStation = pollutionStationLabel(selectedIncident)

  const loadTraceContext = useCallback((incident: IncidentDetails) => {
    const requestId = ++traceRequestIdRef.current
    setIsLoadingTrace(true)
    setEnvironmentalData(null)
    setEnvironmentalError(null)
    setRiskAssessment(null)
    setRiskError(null)

    void Promise.allSettled([
      fetchEnvironmentalData(incident.latitude, incident.longitude),
      isAirPollutionEvent(incident)
        ? Promise.resolve(null)
        : fetchCurrentRiskAssessment(incident.latitude, incident.longitude),
    ]).then(([environmentResult, riskResult]) => {
      if (traceRequestIdRef.current !== requestId) return
      if (environmentResult.status === 'fulfilled') {
        setEnvironmentalData(environmentResult.value)
      } else {
        setEnvironmentalError(
          environmentResult.reason instanceof Error
            ? environmentResult.reason.message
            : 'Environmental trace is unavailable',
        )
      }

      if (riskResult.status === 'fulfilled' && riskResult.value) {
        setRiskAssessment(riskResult.value)
      } else if (riskResult.status === 'rejected') {
        setRiskError(
          riskResult.reason instanceof Error
            ? riskResult.reason.message
            : 'Risk metadata is unavailable',
        )
      }
    }).finally(() => {
      if (traceRequestIdRef.current === requestId) setIsLoadingTrace(false)
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
        if (firstIncident) loadTraceContext(firstIncident)
      })
      .catch((reason: unknown) => {
        if (!active) return
        setIncidentError(
          reason instanceof Error ? reason.message : 'Detected-event audit context is unavailable',
        )
      })
      .finally(() => {
        if (active) setIsLoadingIncident(false)
      })

    return () => {
      active = false
    }
  }, [loadTraceContext])

  const selectIncident = (incident: IncidentDetails) => {
    setSelectedIncident(incident)
    loadTraceContext(incident)
  }

  const sources = useMemo<DataSourceTrace[]>(() => [
    {
      source: 'Detected events endpoint',
      role: 'Detected-event and recommendation context',
      state: sourceState(detectionResponse?.metadata.collection_status),
      status: detectionResponse?.metadata.collection_status || 'No response available',
      timestamp: detectionResponse?.metadata.timestamp,
    },
    {
      source: environmentalData?.metadata.services.weather.source || 'Open-Meteo',
      role: 'Environmental context collected for this audit view',
      state: environmentalError
        ? 'unavailable'
        : sourceState(environmentalData?.metadata.services.weather.status),
      status: environmentalError
        || environmentalData?.metadata.services.weather.status
        || 'No response available',
      timestamp: environmentalData?.metadata.timestamp,
    },
    {
      source: environmentalData?.metadata.services.geospatial.source || 'OpenStreetMap / Overpass',
      role: 'Live supplemental geographic context requested for this audit view',
      state: environmentalError
        ? 'unavailable'
        : sourceState(environmentalData?.metadata.services.geospatial.status),
      status: environmentalError
        || environmentalData?.metadata.services.geospatial.status
        || 'No response available',
      timestamp: environmentalData?.metadata.timestamp,
    },
    ...(selectedIsPollution ? [] : [
      {
        source: 'EcoGuard current-risk model',
        role: 'Point conditions-based fire-risk estimate; separate from event detection',
        state: riskError || riskAssessment?.current_risk.status !== 'available'
          ? 'unavailable' as const
          : 'available' as const,
        status: riskError
          || riskAssessment?.current_risk.reason
          || riskAssessment?.current_risk.status
          || 'No response available',
      },
      {
        source: 'EcoGuard national current-risk scan',
        role: 'National fire-risk context; separate from detected incidents',
        state: nationalRiskError || nationalRiskScan?.status === 'unavailable'
          ? 'unavailable' as const
          : nationalRiskScan?.status === 'partial'
            ? 'partial' as const
            : nationalRiskScan ? 'available' as const : 'unavailable' as const,
        status: nationalRiskError || nationalRiskScan?.status || 'No response available',
        timestamp: nationalRiskScan?.evaluation_time,
      },
    ]),
    ...(selectedIsPollution && selectedIncident?.spatial_context ? [{
      source: selectedIncident.spatial_context.source || 'Event-supplied spatial context',
      role: 'Spatial context supplied with this pollution candidate; proximity does not confirm exposure',
      state: sourceState(selectedIncident.spatial_context.status),
      status: selectedIncident.spatial_context.status,
      timestamp: selectedIncident.spatial_context.collected_at,
    }] : []),
    {
      source: 'RainViewer',
      role: 'Available visualization integration; not queried or traced to this incident here',
      state: 'not-used',
      status: 'Not used in this audit request',
    },
    ...(selectedIsPollution ? [] : [{
      source: 'GWIS / EFFIS',
      role: 'Available fire-danger visualization; not traced to this incident assessment',
      state: 'not-used' as const,
      status: 'Not used in this audit request',
    }]),
    {
      source: selectedIsPollution
        ? pollutionStation ?? 'Air-pollution source'
        : selectedIncident?.detection_source
          || detectionResponse?.metadata.services.detection?.source
          || 'NASA FIRMS',
      role: selectedIsPollution
        ? 'Observation provenance supplied with the air-pollution anomaly'
        : 'Satellite detection source used by the detected-events pipeline; raw hotspots are not exposed separately',
      state: sourceState(selectedIsPollution
        ? selectedIncident?.air_pollution_runtime?.status
        : detectionResponse?.metadata.services.detection?.status),
      status: selectedIsPollution
        ? selectedIncident?.air_pollution_runtime?.status || 'No pollution runtime status available'
        : detectionResponse?.metadata.services.detection?.status || 'No response available',
    },
    {
      source: 'Telegram emergency intelligence',
      role: 'Potential social/open intelligence evidence',
      state: 'unavailable',
      status: 'Not connected to frontend event trace',
    },
  ], [
    detectionResponse,
    environmentalData,
    environmentalError,
    nationalRiskError,
    nationalRiskScan,
    riskAssessment,
    riskError,
    selectedIsPollution,
    pollutionStation,
    selectedIncident,
  ])

  const infrastructureCount = environmentalData
    ? (environmentalData.geospatial_context.nearby_hospitals?.length ?? 0)
      + (environmentalData.geospatial_context.nearby_police_stations?.length ?? 0)
      + (environmentalData.geospatial_context.nearby_fire_stations?.length ?? 0)
    : 0

  const agentDetail = (role: typeof AGENT_ROLES[number]) => {
    switch (role) {
      case 'Data Collection Agents':
        return environmentalData
          ? `Observed context response: ${environmentalData.metadata.collection_status}. Runtime status unavailable.`
          : 'No context output available. Runtime status unavailable.'
      case 'Shared Data Layer / PostGIS':
        return 'Intended shared data layer; database connection and runtime status are not exposed by this frontend contract.'
      case 'Anomaly Detectors':
        if (selectedIsPollution && selectedIncident?.anomaly) {
          return `Air-pollution anomaly supplied with ${selectedIncident.anomaly.supporting_evidence?.length ?? 0} supporting evidence record(s).`
        }
        return detectionResponse?.metadata.services.detection
          ? `Observed pipeline status: ${detectionResponse.metadata.services.detection.status}; source: ${detectionResponse.metadata.services.detection.source || 'not reported'}.`
          : 'No detection output or service metadata is available.'
      case 'Coordinator / Strainer':
        if (selectedIsPollution && selectedIncident?.correlation_evidence) {
          return `Correlation candidate evidence supplied; candidate match: ${selectedIncident.correlation_evidence.candidate_match}. This is not causation or final incident creation.`
        }
        return 'Intended to correlate, deduplicate and group anomalies into incidents. Generic correlation output and runtime status are not currently exposed.'
      case 'Emergency / Non-emergency Routing':
        return 'Intended routing stage after Coordinator correlation; no routing decision or runtime status is exposed here.'
      case 'Resource Allocation / Response Implementation':
        if (selectedIsPollution) {
          return 'No pollution resource-allocation or operational implementation output is exposed.'
        }
        return `Resource selection status: ${selectedIncident?.allocated_resources?.status ?? detectionResponse?.metadata.services.resource_allocation?.status ?? 'Not provided'}. Selected facilities are recommended response sources; operational availability and dispatch are not exposed.`
      case 'Response Planning':
        if (selectedIsPollution) {
          return `Grounded pollution planning status: ${pollutionPlan?.status ?? 'not provided'}. Recommendations are decision support only.`
        }
        return selectedIncident?.planning_status
          ? `Observed planning status: ${selectedIncident.planning_status}; analysis status: ${selectedIncident.analysis_status || 'not provided'}. Grounded outputs and citations are shown where supplied; Coordinator routing and dispatch are not implied.`
          : `No response-plan status is available. Detected-event analysis status: ${selectedIncident?.analysis_status || 'not provided'}.`
    }
  }

  const detectionStatus = detectionResponse?.metadata.services.detection?.status
  const detectionFailed =
    detectionResponse?.metadata.collection_status === 'failed' || detectionStatus === 'failed'
  const responseActions = selectedIncident?.response_actions ?? []
  const protocolCitations = selectedIsPollution
    ? pollutionPlan?.protocol_references ?? []
    : selectedIncident?.protocol_citations ?? []
  const evidenceGaps = selectedIsPollution
    ? pollutionPlan?.evidence_gaps ?? []
    : selectedIncident?.evidence_gaps ?? []

  return (
    <main className="audit-workspace">
      <header className="audit-workspace__header">
        <p className="audit-workspace__eyebrow">Decision traceability</p>
        <h1>Explanation &amp; Audit</h1>
        <p>
          Distinguish real source context and model metadata from demonstration fields,
          unavailable evidence, and unsupported audit capabilities before acting.
        </p>
      </header>

      <div className="audit-workspace__warning" role="status">
        <strong>Grounded output is not hidden reasoning.</strong> When analysis succeeds, the
        explanation and verified citations come from the detected-events pipeline. Prompts,
        chain-of-thought, model conversations, and operator audit history are not exposed.
      </div>

      <section className="audit-panel" aria-labelledby="audit-context-title">
        <div className="audit-panel__heading">
          <div>
            <p className="audit-panel__label">Detected event / recommendation context</p>
            <h2 id="audit-context-title">Selected record</h2>
          </div>
          {incidents.length > 1 && (
            <label className="audit-selector">
              Detected event
              <select
                value={selectedIncident ? eventSelectionKey(selectedIncident) : ''}
                onChange={(event) => {
                  const incident = eventBySelectionKey(incidents, event.target.value)
                  if (incident) selectIncident(incident)
                }}
              >
                {incidents.map((incident) => (
                  <option key={eventSelectionKey(incident)} value={eventSelectionKey(incident)}>{incident.title}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        {isLoadingIncident && (
          <p className="audit-message">
            Awaiting event detection, risk analysis, and response planning output. This can take up to 90 seconds.
          </p>
        )}
        {incidentError && <p className="audit-message audit-message--error">{incidentError}</p>}
        {!isLoadingIncident && !incidentError && !selectedIncident && (
          <p className="audit-message">
            {detectionFailed
              ? 'The detection provider could not complete the current scan; no detected-event audit is available.'
              : 'The current scan completed with no detected event or anomaly candidate to audit.'}
          </p>
        )}
        {selectedIncident && (
          <div className="audit-facts">
            <div><span>Event type</span><strong>{selectedIsPollution ? 'Air Pollution' : selectedIncident.type || 'Not provided'}</strong></div>
            <div><span>Location</span><strong>{selectedIncident.latitude.toFixed(4)}, {selectedIncident.longitude.toFixed(4)}</strong></div>
            {selectedIsPollution && pollutionObservation && <div><span>Observation</span><strong>{pollutionObservation.pollutant} · {pollutionObservation.value} {pollutionObservation.unit}</strong></div>}
            <div><span>{selectedIsPollution ? 'Anomaly severity' : 'Reported event risk'}</span><strong>{selectedIsPollution ? selectedIncident.anomaly?.severity ?? 'Not provided' : selectedIncident.risk_level || 'Not assessed'}</strong></div>
            {!selectedIsPollution && <div><span>Risk score</span><strong>{selectedIncident.risk_score ?? 'Not assessed'}</strong></div>}
            <div><span>Detection status</span><strong>{selectedIsPollution ? selectedIncident.air_pollution_runtime?.status ?? 'Not provided' : detectionStatus || 'Not provided'}</strong></div>
            {!selectedIsPollution && <div><span>Analysis status</span><strong>{selectedIncident.analysis_status || 'Not provided'}</strong></div>}
            <div><span>Planning status</span><strong>{selectedIsPollution ? pollutionPlan?.status ?? 'Not provided' : selectedIncident.planning_status || 'Not provided'}</strong></div>
            <div><span>Confidence</span><strong>{selectedIsPollution && typeof selectedIncident.anomaly?.confidence === 'number' ? `${Math.round(selectedIncident.anomaly.confidence * 100)}%` : selectedIncident.confidence || 'Not provided'}</strong></div>
          </div>
        )}
      </section>

      {selectedIsPollution && selectedIncident?.anomaly && (
        <section className="audit-panel" aria-labelledby="pollution-trace-title">
          <p className="audit-panel__label">Air-pollution trace</p>
          <h2 id="pollution-trace-title">Detection, spatial and correlation evidence</h2>
          <div className="audit-evidence-grid">
            <div><span>Observed</span><strong>{formatEventTimestamp(selectedIncident.anomaly.observed_at) ?? 'Unavailable'}</strong></div>
            <div><span>Station / source</span><strong>{pollutionStation ?? 'Unavailable'}</strong></div>
            <div><span>Spatial lookup</span><strong>{selectedIncident.spatial_context?.status ?? 'Not supplied'}</strong></div>
            <div><span>Nearby settlements</span><strong>{selectedIncident.spatial_context?.nearby_settlements?.length ?? 'Not supplied'}</strong></div>
            <div><span>Nearby roads</span><strong>{selectedIncident.spatial_context?.nearby_roads?.length ?? 'Not supplied'}</strong></div>
            <div><span>Correlation candidate match</span><strong>{selectedIncident.correlation_evidence ? String(selectedIncident.correlation_evidence.candidate_match) : 'Not supplied'}</strong></div>
          </div>
          {selectedIncident.anomaly.anomaly_reasons?.length ? (
            <div className="model-factors"><h3>Why EcoGuard flagged this anomaly</h3><ul>{selectedIncident.anomaly.anomaly_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>
          ) : null}
          {selectedIncident.correlation_evidence && (
            <div className="model-factors">
              <h3>Correlation signals</h3>
              <p>Engineering candidate evidence only; it does not establish causation or a common incident.</p>
              <ul>{selectedIncident.correlation_evidence.matching_signals.map((signal) => <li key={signal}>{displayTraceValue(signal)}</li>)}</ul>
            </div>
          )}
          <p className="audit-panel__note">Nearby places and roads are proximity context only. They do not confirm exposure, pollution movement, or source attribution. The lookup radius is not an affected-area boundary.</p>
        </section>
      )}

      <section className="audit-panel" aria-labelledby="explanation-title">
        <p className="audit-panel__label">Human-readable explanation</p>
        <h2 id="explanation-title">Available explanation text</h2>
        <div className="audit-explanation">
          <span>
            {selectedIsPollution
              ? 'Deterministic anomaly explanation'
              : selectedIncident?.analysis_status === 'success'
                ? 'Grounded pipeline explanation'
              : 'Explanation unavailable or incomplete'}
          </span>
          <p>{selectedIsPollution ? selectedIncident?.anomaly?.explanation || 'No anomaly explanation is available.' : selectedIncident?.explanation || 'No explanation text is available.'}</p>
        </div>
      </section>

      <div className="audit-workspace__columns">
        <section className="audit-panel" aria-labelledby="evidence-summary-title">
          <p className="audit-panel__label">Evidence summary</p>
          <h2 id="evidence-summary-title">Context available to the operator</h2>
          <p className="audit-panel__note">
            Live supplemental context below is retrieved for the selected coordinates. Event-supplied
            pollution context remains available independently. Verified protocol citations identify
            the textual sources grounding pipeline outputs.
          </p>
          {isLoadingTrace && <p className="audit-message">Collecting traceable context…</p>}
          <div className="audit-evidence-grid">
            <div><span>Temperature</span><strong>{environmentalData?.weather?.current?.temperature_c ?? 'Unavailable'}</strong></div>
            <div><span>Humidity</span><strong>{environmentalData?.weather?.current?.humidity_percent ?? 'Unavailable'}</strong></div>
            <div><span>Terrain</span><strong>{String(environmentalData?.geospatial_context.terrain_type || 'Unavailable')}</strong></div>
            <div><span>Region</span><strong>{String(environmentalData?.geospatial_context.region_type || 'Unavailable')}</strong></div>
            <div><span>Nearby infrastructure</span><strong>{environmentalData ? infrastructureCount : 'Unavailable'}</strong></div>
            <div><span>Detection source</span><strong>{selectedIsPollution ? pollutionStation ?? 'Unavailable' : selectedIncident?.detection_source || detectionResponse?.metadata.services.detection?.source || 'Unavailable'}</strong></div>
            {selectedIsPollution && <div><span>Event-supplied spatial context</span><strong>{selectedIncident?.spatial_context?.status ?? 'Not supplied'}</strong></div>}
          </div>
          {evidenceGaps.length > 0 && (
            <div className="model-factors">
              <h3>Evidence gaps reported by analysis</h3>
              <ul>{evidenceGaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>
            </div>
          )}
        </section>

        <section className="audit-panel" aria-labelledby="limitations-title">
          <p className="audit-panel__label">Confidence / limitations</p>
          <h2 id="limitations-title">Known limitations</h2>
          <ul className="audit-limitations">
            <li>Confidence is shown only when supplied by the detected-events response.</li>
            <li>Suggested units are not verified allocations, availability, or dispatch assignments.</li>
            <li>{selectedIsPollution ? 'Nearby geographic features do not confirm exposure, movement, or source attribution.' : 'Raw FIRMS hotspots and Telegram messages are not exposed as frontend records.'}</li>
            {!selectedIsPollution && <li>Model factors are associations with an estimate, not causal explanations.</li>}
            <li>No prompt trace, hidden reasoning, audit history, or operator approval history exists.</li>
          </ul>
        </section>
      </div>

      <section className="audit-panel" aria-labelledby="grounded-output-title">
        <p className="audit-panel__label">Grounded pipeline output</p>
        <h2 id="grounded-output-title">Response actions and verified citations</h2>
        {selectedIsPollution && pollutionPlan?.actions?.length ? (
          <ol className="audit-limitations">
            {pollutionPlan.actions.map((action) => (
              <li key={`${action.resource_type}-${action.recommendation}`}>
                <strong>{displayTraceValue(action.timeframe)} · {displayTraceValue(action.priority)}</strong>
                {' · '}{displayTraceValue(action.responsible_authority_type)} — {action.recommendation}
              </li>
            ))}
          </ol>
        ) : responseActions.length > 0 ? (
          <ol className="audit-limitations">
            {responseActions.map((action) => (
              <li key={`${action.timeframe}-${action.responsible_unit}-${action.action}`}>
                <strong>{action.timeframe.replace(/_/g, ' ')}</strong>
                {' · '}{action.responsible_unit.replace(/_/g, ' ')} — {action.action}
              </li>
            ))}
          </ol>
        ) : (
          <p className="audit-message">
            No structured response actions are available for this detected event.
          </p>
        )}
        {protocolCitations.length > 0 ? (
          <div className="audit-source-grid">
            {protocolCitations.map((citation) => (
              <article key={citation.chunk_id}>
                <div className="audit-source__heading">
                  <h3>{citation.document_title}</h3>
                  <span className="audit-state audit-state--available">verified</span>
                </div>
                <p>“{citation.quoted_text}”</p>
                <dl>
                  <div><dt>Supports</dt><dd>{citation.supports}</dd></div>
                  <div><dt>Section</dt><dd>{citation.heading_path || 'Not provided'}</dd></div>
                  <div>
                    <dt>Source</dt>
                    <dd>
                      {citation.source_url ? (
                        <a href={citation.source_url} target="_blank" rel="noreferrer">
                          Open source document
                        </a>
                      ) : 'No source URL provided'}
                    </dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        ) : (
          <p className="audit-message">No verified protocol citations are available.</p>
        )}
      </section>

      <section className="audit-panel" aria-labelledby="source-trace-title">
        <p className="audit-panel__label">Data source traceability</p>
        <h2 id="source-trace-title">Source status and provenance</h2>
        <div className="audit-source-grid">
          {sources.map((source) => (
            <article key={source.source}>
              <div className="audit-source__heading">
                <h3>{source.source}</h3>
                <span className={`audit-state audit-state--${source.state}`}>{source.state.replace('-', ' ')}</span>
              </div>
              <p>{source.role}</p>
              <dl>
                <div><dt>Status</dt><dd>{source.status}</dd></div>
                <div><dt>Timestamp</dt><dd>{formatTimestamp(source.timestamp)}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      {!selectedIsPollution && <section className="audit-panel" aria-labelledby="model-metadata-title">
        <p className="audit-panel__label">Model / risk metadata</p>
        <h2 id="model-metadata-title">Current-risk trace</h2>
        <p className="audit-panel__note">
          Current risk estimates environmental conditions and does not assert that an incident was detected.
        </p>
        <div className="model-metadata">
          <div><span>Point-risk status</span><strong>{riskError || riskAssessment?.current_risk.status || 'Unavailable'}</strong></div>
          <div><span>Point-risk estimate</span><strong>{riskAssessment?.current_risk.score !== null && riskAssessment?.current_risk.score !== undefined ? `${(riskAssessment.current_risk.score * 100).toFixed(1)}%` : 'Unavailable'}</strong></div>
          <div><span>Point-risk level</span><strong>{riskAssessment?.current_risk.level || 'Unavailable'}</strong></div>
          <div><span>Model version</span><strong>{riskAssessment?.current_risk.model_version || 'Unavailable'}</strong></div>
          <div><span>Risk semantics</span><strong>{riskAssessment?.current_risk.semantics || 'Unavailable'}</strong></div>
          <div><span>Runtime input gaps</span><strong>{riskAssessment?.current_risk.missing_runtime_inputs.length ? riskAssessment.current_risk.missing_runtime_inputs.join(', ') : 'None reported'}</strong></div>
          <div><span>National evaluation</span><strong>{formatTimestamp(nationalRiskScan?.evaluation_time)}</strong></div>
          <div><span>National semantics</span><strong>{nationalRiskScan?.semantics || 'Unavailable'}</strong></div>
          <div><span>Snapshot freshness</span><strong>{nationalRiskError || (nationalRiskScan?.refresh_metadata?.stale === true ? 'Stale' : nationalRiskScan ? 'Not marked stale' : 'Unavailable')}</strong></div>
          <div><span>Last successful refresh</span><strong>{formatTimestamp(nationalRiskScan?.refresh_metadata?.last_successful_refresh_at_utc)}</strong></div>
        </div>
        <div className="model-factors">
          <h3>Main model-associated factors</h3>
          <p>These factors are not causal explanations.</p>
          {riskAssessment?.current_risk.main_factors.length ? (
            <ul>
              {riskAssessment.current_risk.main_factors.map((factor) => (
                <li key={factor.feature}><strong>{factor.feature}</strong><span>{factor.statement}</span></li>
              ))}
            </ul>
          ) : (
            <p className="audit-message">No model-associated factors were returned.</p>
          )}
        </div>
      </section>}

      <section className="audit-panel" aria-labelledby="agent-trace-title">
        <p className="audit-panel__label">Agent traceability</p>
        <h2 id="agent-trace-title">Observable architectural outputs</h2>
        <p className="audit-panel__note">Intended architecture with observed service outputs where supplied. Detection candidates are not confirmed correlated incidents; PostGIS, Coordinator and routing runtime are not exposed here.</p>
        <ol className="audit-agent-list">
          {AGENT_ROLES.map((role) => (
            <li key={role}><strong>{role}</strong><span>{agentDetail(role)}</span></li>
          ))}
        </ol>
      </section>

      <section className="audit-panel" aria-labelledby="report-actions-title">
        <p className="audit-panel__label">Report / audit actions</p>
        <h2 id="report-actions-title">Operational actions unavailable</h2>
        <p className="audit-panel__note">
          No backend contract exists for report export, incident-log storage, or report delivery.
        </p>
        <div className="audit-actions">
          <button type="button" disabled>Export report · unavailable</button>
          <button type="button" disabled>Save incident log · unavailable</button>
          <button type="button" disabled>Send / share report · unavailable</button>
        </div>
      </section>

      <nav className="audit-workflow" aria-label="Audit workflow">
        <Link to="/response-planning">← Back to Response Planning</Link>
        <Link to="/data-layers">Inspect Data Sources</Link>
      </nav>
    </main>
  )
}

export default ExplanationAudit
