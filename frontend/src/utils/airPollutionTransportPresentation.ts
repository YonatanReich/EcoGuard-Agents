export type TransportExclusionReason =
  | 'outside_transport_corridor'
  | 'upwind_of_origin'
  | 'beyond_screening_range'
  | 'insufficient_wind_evidence'

type RankedSettlement = {
  inside_transport_corridor: boolean
  rank?: number | null
}

export const TRANSPORT_SCREENING_SUMMARY = (
  'Estimated atmospheric transport screening. Exposure is not confirmed.'
)

export const TRANSPORT_PRESENTATION_LIMITATIONS = [
  'The analysis origin is currently the monitoring location and is not necessarily the pollution emission source.',
  'This is geometric atmospheric transport screening, not a physical plume or concentration forecast.',
  'Exposure is not confirmed.',
  'Settlement ranking represents geometric downwind relevance only; it does not express likelihood or risk severity.',
  'Kinematic transport duration is a screening estimate, not an ETA or confirmed arrival time.',
] as const

function compactNumber(value: number, decimals = 1): string {
  const rounded = Math.round(value * (10 ** decimals)) / (10 ** decimals)
  return Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(decimals)
}

/** Format a backend-computed distance without deriving new spatial values. */
export function formatTransportDistance(distanceM: number): string {
  if (!Number.isFinite(distanceM)) return 'Unavailable'
  return Math.abs(distanceM) >= 1000
    ? `${compactNumber(distanceM / 1000)} km`
    : `${compactNumber(distanceM, 0)} m`
}

/** Format a backend-computed angle without recalculating direction. */
export function formatTransportAngle(angleDeg: number): string {
  return Number.isFinite(angleDeg) ? `${compactNumber(angleDeg)}°` : 'Unavailable'
}

/** Format only the nullable backend duration; this never computes transport time. */
export function formatTransportDuration(durationSeconds?: number | null): string {
  if (durationSeconds == null || !Number.isFinite(durationSeconds)) {
    return 'Transport duration screening unavailable'
  }
  if (durationSeconds < 60) return '~<1 min'
  return `~${compactNumber(durationSeconds / 60, 0)} min`
}

export function transportExclusionReasonLabel(
  reason?: string | null,
): string | null {
  const labels: Record<TransportExclusionReason, string> = {
    outside_transport_corridor: 'Outside screening angle',
    upwind_of_origin: 'Upwind of analysis origin',
    beyond_screening_range: 'Beyond configured screening distance',
    insufficient_wind_evidence: 'Insufficient wind evidence',
  }
  return reason && reason in labels
    ? labels[reason as TransportExclusionReason]
    : null
}

export function transportCorridorMethodLabel(method: string): string {
  const labels: Record<string, string> = {
    fixed_angle_screening: 'Fixed-angle screening',
    direction_variability_screening: 'Direction-variability screening',
    model_derived_screening: 'Model-derived screening',
  }
  return labels[method] ?? 'Transport screening'
}

/** Preserve backend array order and backend ranks; never assign or sort ranks. */
export function inCorridorRankedSettlements<T extends RankedSettlement>(
  settlements: readonly T[],
): T[] {
  return settlements.filter(
    (settlement) => settlement.inside_transport_corridor && settlement.rank != null,
  )
}

export function outsideCorridorSettlements<T extends RankedSettlement>(
  settlements: readonly T[],
): T[] {
  return settlements.filter((settlement) => !settlement.inside_transport_corridor)
}

export function settlementCandidateScopeLimitation(
  lookupRadiusKm?: number | null,
): string {
  const radius = lookupRadiusKm != null && Number.isFinite(lookupRadiusKm)
    ? ` (${compactNumber(lookupRadiusKm)} km for this event)`
    : ''
  return (
    `Settlement screening is limited to candidates available from the current `
    + `spatial-context search${radius} and may not include settlements farther `
    + 'along the corridor.'
  )
}
