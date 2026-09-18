import type {
  EventClassification,
  HazardKind,
  SharedEvent,
} from '../types/events'

export type HazardStyle = {
  kind: HazardKind
  label: string
  color: string
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

export function hazardOf(event: SharedEvent): HazardStyle {
  return HAZARDS[event.type]
}

export function classify(event: SharedEvent): EventClassification {
  // Air Pollution is advisory by domain contract, regardless of source-native
  // AQI category or historical anomaly evidence.
  if (event.type === 'air_pollution') return 'advisory'
  return event.classification
}

/** Fire classification remains inferred until the shared event feed exists. */
export const CLASSIFICATION_IS_INFERRED = true

export type { HazardKind } from '../types/events'
