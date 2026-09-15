/**
 * The one place hazard colour and emergency classification are decided.
 *
 * The legend, the event cards and the map markers all read from here, which is
 * what makes them agree. A colour defined twice is a colour that will drift.
 */

import type { RiskEvent } from '../pages/Dashboard'


export type HazardKind = 'fire' | 'air_pollution' | 'flood' | 'other'

export type Classification = 'emergency' | 'advisory'


export type HazardStyle = {
  kind: HazardKind
  label: string
  /** Card border, marker fill, legend swatch — the identity colour. */
  color: string
  /** Same hue, translucent, for the pulsing halo on the map. */
  halo: string
}


export const HAZARDS: Record<HazardKind, HazardStyle> = {
  fire: {
    kind: 'fire',
    label: 'Fire',
    color: '#f97316',
    halo: 'rgba(249, 115, 22, 0.45)',
  },
  air_pollution: {
    kind: 'air_pollution',
    label: 'Air pollution',
    color: '#a855f7',
    halo: 'rgba(168, 85, 247, 0.45)',
  },
  flood: {
    kind: 'flood',
    label: 'Flood',
    color: '#38bdf8',
    halo: 'rgba(56, 189, 248, 0.45)',
  },
  other: {
    kind: 'other',
    label: 'Other',
    color: '#94a3b8',
    halo: 'rgba(148, 163, 184, 0.45)',
  },
}


/** Map the backend's free-text event type onto a known hazard. */
export function hazardOf(event: RiskEvent): HazardStyle {
  const type = (event.type ?? '').toLowerCase()
  if (type.includes('fire')) return HAZARDS.fire
  if (type.includes('air') || type.includes('pollution')) return HAZARDS.air_pollution
  if (type.includes('flood')) return HAZARDS.flood
  return HAZARDS.other
}


/**
 * Emergency or advisory.
 *
 * This is a placeholder for `events.classification`, which the triage stage
 * will set from severity, proximity to population and actionability. Triage
 * does not exist yet, so the panels derive it from the risk band instead.
 *
 * Deliberately one function with one caller-visible name: when triage lands,
 * this body becomes `return event.classification` and nothing else changes.
 *
 * Note this is NOT classification by hazard type. A brush fire in an empty
 * field is not an emergency; an industrial chemical release is. Only severity
 * decides, which is why the colour (hazard) and the panel (urgency) are
 * separate axes here.
 */
export function classify(event: RiskEvent): Classification {
  return event.risk_level === 'critical' || event.risk_level === 'high'
    ? 'emergency'
    : 'advisory'
}


/** True while the classification is inferred rather than supplied by triage. */
export const CLASSIFICATION_IS_INFERRED = true
