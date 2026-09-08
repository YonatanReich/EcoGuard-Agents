import type { AirPollutionObservation } from '../types/airPollution'
import type { IncidentDetails } from '../types/incidents'

export function isAirPollutionEvent(event: IncidentDetails | null | undefined): boolean {
  return Boolean(
    event
    && ((typeof event.type === 'string'
      && event.type.toLowerCase().replace(/[ -]/g, '_') === 'air_pollution')
      || event.anomaly?.anomaly_type === 'air_pollution'),
  )
}

/** UI identity stays stable even when different hazards reuse the same raw ID. */
export function eventSelectionKey(event: IncidentDetails): string {
  const eventType = typeof event.type === 'string' && event.type.trim()
    ? event.type.trim().toLowerCase().replace(/[ -]/g, '_')
    : 'unknown'
  return `${eventType}:${String(event.id)}`
}

export function eventBySelectionKey(
  events: IncidentDetails[],
  key: string,
): IncidentDetails | undefined {
  return events.find((event) => eventSelectionKey(event) === key)
}

export function primaryPollutionObservation(
  event: IncidentDetails | null | undefined,
): AirPollutionObservation | null {
  if (!isAirPollutionEvent(event)) return null
  const observations = event?.anomaly?.pollutant_observations?.filter(
    (observation) => Number.isFinite(observation.value),
  ) ?? []
  if (observations.length === 0) return null
  return observations.reduce((latest, observation) => {
    const latestTime = latest.observed_at ? Date.parse(latest.observed_at) : Number.NaN
    const observationTime = observation.observed_at
      ? Date.parse(observation.observed_at)
      : Number.NaN
    if (Number.isNaN(observationTime)) return latest
    return Number.isNaN(latestTime) || observationTime > latestTime
      ? observation
      : latest
  })
}

export function pollutionStationLabel(event: IncidentDetails | null | undefined): string | null {
  const source = event?.anomaly?.sources?.[0]
  if (!source) return null
  const station = source.metadata?.station_id
  return station ? `${source.source_name} · station ${station}` : source.source_name
}

export function formatEventTimestamp(value?: string | null): string | null {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toLocaleString()
}
