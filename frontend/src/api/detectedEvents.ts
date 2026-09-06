import type {
  DetectedEventsResponse,
  IncidentDetails,
} from '../types/incidents'

const DETECTED_EVENTS_REUSE_MS = 30_000

let inFlightRequest: Promise<DetectedEventsResponse> | null = null
let recentResponse: { value: DetectedEventsResponse; receivedAt: number } | null = null
let latestRequestId = 0

async function requestDetectedEvents(): Promise<DetectedEventsResponse> {
  const response = await fetch('/api/detected-events?include_analysis=true')
  if (!response.ok) throw new Error('Detected event data is unavailable')

  const payload = await response.json() as Partial<DetectedEventsResponse>
  if (!payload.metadata || !payload.query || !Array.isArray(payload.events)) {
    throw new Error('Detected event response is invalid')
  }

  return payload as DetectedEventsResponse
}

export function fetchDetectedEventsResponse(
  options: { forceRefresh?: boolean } = {},
): Promise<DetectedEventsResponse> {
  const now = Date.now()
  if (
    !options.forceRefresh &&
    recentResponse &&
    now - recentResponse.receivedAt < DETECTED_EVENTS_REUSE_MS
  ) {
    return Promise.resolve(recentResponse.value)
  }

  if (!options.forceRefresh && inFlightRequest) return inFlightRequest

  const requestId = ++latestRequestId
  const request = requestDetectedEvents()
    .then((value) => {
      if (requestId === latestRequestId) {
        recentResponse = { value, receivedAt: Date.now() }
      }
      return value
    })
    .finally(() => {
      if (inFlightRequest === request) inFlightRequest = null
    })

  inFlightRequest = request
  return request
}

export async function fetchDetectedEvents(): Promise<IncidentDetails[]> {
  return (await fetchDetectedEventsResponse()).events
}
