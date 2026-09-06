import type { IncidentDetails } from '../types/incidents'

export async function fetchDetectedEvents(): Promise<IncidentDetails[]> {
  const response = await fetch('/api/detected-events')
  if (!response.ok) throw new Error('Detected event data is unavailable')

  const payload = await response.json() as { events?: unknown }
  if (!Array.isArray(payload.events)) {
    throw new Error('Detected event response is invalid')
  }

  return payload.events as IncidentDetails[]
}
