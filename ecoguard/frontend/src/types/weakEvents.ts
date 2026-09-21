/**
 * The uncorroborated lane.
 *
 * Kept in its own module and its own type rather than widened into
 * SharedEvent, for the same reason the API serves it from its own endpoint: a
 * weak event has no risk assessment, no plan and no allocation, and a type
 * that allowed it to flow where a SharedEvent flows would make every consumer
 * responsible for remembering the difference.
 */

export type WeakHazard = 'fire' | 'flood' | 'earthquake' | 'air_quality'

export type WeakEventReport = {
  source_id: string
  tier: string
  claim: string | null
  location_text: string | null
  observed_at: string | null
}

export type WeakEvent = {
  id: string
  hazard: WeakHazard
  status: string
  latitude: number | null
  longitude: number | null
  precision_m: number | null
  location_text: string | null
  first_seen_at: string
  last_seen_at: string
  expires_at: string
  expires_in_seconds: number
  reports: WeakEventReport[]
  would_confirm: string[]
}

export type WeakEventFeed = {
  weak_events: WeakEvent[]
}

/** Only the ones with a position can go on the map; the rest are list-only. */
export function mappable(weakEvent: WeakEvent): boolean {
  return weakEvent.latitude !== null && weakEvent.longitude !== null
}
