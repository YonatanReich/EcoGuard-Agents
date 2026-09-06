import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchDetectedEventsResponse } from '../api/detectedEvents'
import { fetchEnvironmentalData } from '../api/environmentalData'
import { fetchCurrentRiskAssessment } from '../api/fireRisk'
import { useNationalRiskScan } from '../hooks/useNationalRiskScan'
import type { EnvironmentalData } from '../types/environmentalData'
import type { DetectedEventsResponse, IncidentDetails } from '../types/incidents'
import type { FireRiskAssessment } from '../types/riskAnalysis'

import './visuals/explanation-audit.css'

type TraceState = 'available' | 'partial' | 'demo' | 'unavailable' | 'not-used'

type DataSourceTrace = {
  source: string
  role: string
  state: TraceState
  status: string
  timestamp?: string | null
}

const AGENT_ROLES = [
  'Data Collection Agent',
  'Event Detection Agent',
  'Risk Analysis Agent',
  'Resource Allocation Agent',
  'Response Planning Agent',
  'LLM Coordination Agent',
] as const

function formatTimestamp(value?: string | null) {
  if (!value) return 'Not available'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'Not available' : parsed.toLocaleString()
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
  const { scan: nationalRiskScan, error: nationalRiskError } = useNationalRiskScan()

  const loadTraceContext = useCallback((incident: IncidentDetails) => {
    setIsLoadingTrace(true)
    setEnvironmentalData(null)
    setEnvironmentalError(null)
    setRiskAssessment(null)
    setRiskError(null)

    void Promise.allSettled([
      fetchEnvironmentalData(incident.latitude, incident.longitude),
      fetchCurrentRiskAssessment(incident.latitude, incident.longitude),
    ]).then(([environmentResult, riskResult]) => {
      if (environmentResult.status === 'fulfilled') {
        setEnvironmentalData(environmentResult.value)
      } else {
        setEnvironmentalError(
          environmentResult.reason instanceof Error
            ? environmentResult.reason.message
            : 'Environmental trace is unavailable',
        )
      }

      if (riskResult.status === 'fulfilled') {
        setRiskAssessment(riskResult.value)
      } else {
        setRiskError(
          riskResult.reason instanceof Error
            ? riskResult.reason.message
            : 'Risk metadata is unavailable',
        )
      }
    }).finally(() => setIsLoadingTrace(false))
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
          reason instanceof Error ? reason.message : 'Incident audit context is unavailable',
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
      role: 'Incident and recommendation context',
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
      role: 'Geographic and infrastructure context collected for this audit view',
      state: environmentalError
        ? 'unavailable'
        : sourceState(environmentalData?.metadata.services.geospatial.status),
      status: environmentalError
        || environmentalData?.metadata.services.geospatial.status
        || 'No response available',
      timestamp: environmentalData?.metadata.timestamp,
    },
    {
      source: 'EcoGuard current-risk model',
      role: 'Point conditions-based model estimate; separate from event detection',
      state: riskError || riskAssessment?.current_risk.status !== 'available'
        ? 'unavailable'
        : 'available',
      status: riskError
        || riskAssessment?.current_risk.reason
        || riskAssessment?.current_risk.status
        || 'No response available',
    },
    {
      source: 'EcoGuard national current-risk scan',
      role: 'National conditions-based risk context; separate from detected incidents',
      state: nationalRiskError || nationalRiskScan?.status === 'unavailable'
        ? 'unavailable'
        : nationalRiskScan?.status === 'partial'
          ? 'partial'
          : nationalRiskScan ? 'available' : 'unavailable',
      status: nationalRiskError || nationalRiskScan?.status || 'No response available',
      timestamp: nationalRiskScan?.evaluation_time,
    },
    {
      source: 'RainViewer',
      role: 'Available visualization integration; not queried or traced to this incident here',
      state: 'not-used',
      status: 'Not used in this audit request',
    },
    {
      source: 'GWIS / EFFIS',
      role: 'Available fire-danger visualization; not traced to this incident assessment',
      state: 'not-used',
      status: 'Not used in this audit request',
    },
    {
      source: 'NASA FIRMS',
      role: 'Satellite detection source used by the detected-events pipeline; raw hotspots are not exposed separately',
      state: sourceState(detectionResponse?.metadata.services.detection?.status),
      status: detectionResponse?.metadata.services.detection?.status || 'No response available',
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
  ])

  const infrastructureCount = environmentalData
    ? (environmentalData.geospatial_context.nearby_hospitals?.length ?? 0)
      + (environmentalData.geospatial_context.nearby_police_stations?.length ?? 0)
      + (environmentalData.geospatial_context.nearby_fire_stations?.length ?? 0)
    : 0

  const agentDetail = (role: typeof AGENT_ROLES[number]) => {
    switch (role) {
      case 'Data Collection Agent':
        return environmentalData
          ? `Observed context response: ${environmentalData.metadata.collection_status}. Runtime status unavailable.`
          : 'No context output available. Runtime status unavailable.'
      case 'Event Detection Agent':
        return detectionResponse?.metadata.services.detection
          ? `Observed pipeline status: ${detectionResponse.metadata.services.detection.status}; source: ${detectionResponse.metadata.services.detection.source || 'not reported'}.`
          : 'No detection output or service metadata is available.'
      case 'Risk Analysis Agent':
        return selectedIncident?.analysis_status
          ? `Detected-event analysis status: ${selectedIncident.analysis_status}.`
          : 'No detected-event risk analysis output is available.'
      case 'Resource Allocation Agent':
        return selectedIncident?.recommended_units?.length
          ? 'Suggested units are observable; no verified allocation or dispatch status exists.'
          : 'No observable allocation output or runtime status.'
      case 'Response Planning Agent':
        return selectedIncident?.planning_status
          ? `Detected-event planning status: ${selectedIncident.planning_status}; no dispatch status is implied.`
          : 'No observable response-plan output or runtime status.'
      case 'LLM Coordination Agent':
        return selectedIncident?.protocol_citations?.length
          ? 'Grounded output and verified citations are observable; prompts, hidden reasoning, and runtime traces are not exposed.'
          : 'No prompt trace, hidden reasoning, model conversation, or runtime status is exposed.'
    }
  }

  const detectionStatus = detectionResponse?.metadata.services.detection?.status
  const detectionFailed =
    detectionResponse?.metadata.collection_status === 'failed' || detectionStatus === 'failed'
  const responseActions = selectedIncident?.response_actions ?? []
  const protocolCitations = selectedIncident?.protocol_citations ?? []
  const evidenceGaps = selectedIncident?.evidence_gaps ?? []

  return (
    <main className="audit-workspace">
      <header className="audit-workspace__header">
        <p className="audit-workspace__eyebrow">Decision traceability</p>
        <h1>LLM Explanation &amp; Audit</h1>
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
            <p className="audit-panel__label">Incident / recommendation context</p>
            <h2 id="audit-context-title">Selected record</h2>
          </div>
          {incidents.length > 1 && (
            <label className="audit-selector">
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
        {isLoadingIncident && (
          <p className="audit-message">
            Running incident detection, risk analysis, and response planning. This can take up to 90 seconds.
          </p>
        )}
        {incidentError && <p className="audit-message audit-message--error">{incidentError}</p>}
        {!isLoadingIncident && !incidentError && !selectedIncident && (
          <p className="audit-message">
            {detectionFailed
              ? 'The detection provider could not complete the current scan; no incident audit is available.'
              : 'The current scan completed with no active fire incident to audit.'}
          </p>
        )}
        {selectedIncident && (
          <div className="audit-facts">
            <div><span>Event type</span><strong>{selectedIncident.type || 'Not provided'}</strong></div>
            <div><span>Location</span><strong>{selectedIncident.latitude.toFixed(4)}, {selectedIncident.longitude.toFixed(4)}</strong></div>
            <div><span>Incident risk</span><strong>{selectedIncident.risk_level || 'Not assessed'}</strong></div>
            <div><span>Risk score</span><strong>{selectedIncident.risk_score ?? 'Not assessed'}</strong></div>
            <div><span>Detection status</span><strong>{detectionStatus || 'Not provided'}</strong></div>
            <div><span>Analysis status</span><strong>{selectedIncident.analysis_status || 'Not provided'}</strong></div>
            <div><span>Planning status</span><strong>{selectedIncident.planning_status || 'Not provided'}</strong></div>
            <div><span>Confidence</span><strong>{selectedIncident.confidence || 'Not provided'}</strong></div>
          </div>
        )}
      </section>

      <section className="audit-panel" aria-labelledby="explanation-title">
        <p className="audit-panel__label">Human-readable explanation</p>
        <h2 id="explanation-title">Available explanation text</h2>
        <div className="audit-explanation">
          <span>
            {selectedIncident?.analysis_status === 'success'
              ? 'Grounded pipeline explanation'
              : 'Explanation unavailable or incomplete'}
          </span>
          <p>{selectedIncident?.explanation || 'No explanation text is available.'}</p>
        </div>
      </section>

      <div className="audit-workspace__columns">
        <section className="audit-panel" aria-labelledby="evidence-summary-title">
          <p className="audit-panel__label">Evidence summary</p>
          <h2 id="evidence-summary-title">Context available to the operator</h2>
          <p className="audit-panel__note">
            Environmental context below is retrieved for the selected coordinates. Verified
            protocol citations identify the textual sources grounding pipeline outputs.
          </p>
          {isLoadingTrace && <p className="audit-message">Collecting traceable context…</p>}
          <div className="audit-evidence-grid">
            <div><span>Temperature</span><strong>{environmentalData?.weather?.current?.temperature_c ?? 'Unavailable'}</strong></div>
            <div><span>Humidity</span><strong>{environmentalData?.weather?.current?.humidity_percent ?? 'Unavailable'}</strong></div>
            <div><span>Terrain</span><strong>{String(environmentalData?.geospatial_context.terrain_type || 'Unavailable')}</strong></div>
            <div><span>Region</span><strong>{String(environmentalData?.geospatial_context.region_type || 'Unavailable')}</strong></div>
            <div><span>Nearby infrastructure</span><strong>{environmentalData ? infrastructureCount : 'Unavailable'}</strong></div>
            <div><span>Detection source</span><strong>{detectionResponse?.metadata.services.detection?.source || 'Unavailable'}</strong></div>
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
            <li>Raw FIRMS hotspots and Telegram messages are not exposed as frontend records.</li>
            <li>Model factors are associations with an estimate, not causal explanations.</li>
            <li>No prompt trace, hidden reasoning, audit history, or operator approval history exists.</li>
          </ul>
        </section>
      </div>

      <section className="audit-panel" aria-labelledby="grounded-output-title">
        <p className="audit-panel__label">Grounded pipeline output</p>
        <h2 id="grounded-output-title">Response actions and verified citations</h2>
        {responseActions.length > 0 ? (
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
            No structured response actions are available for this incident.
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

      <section className="audit-panel" aria-labelledby="model-metadata-title">
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
      </section>

      <section className="audit-panel" aria-labelledby="agent-trace-title">
        <p className="audit-panel__label">Agent traceability</p>
        <h2 id="agent-trace-title">Observable architectural outputs</h2>
        <p className="audit-panel__note">Runtime execution status is not exposed for any agent.</p>
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
