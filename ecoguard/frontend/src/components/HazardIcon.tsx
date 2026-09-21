/**
 * HazardIcon — one glyph per hazard kind, drawn in currentColor.
 *
 * The legend, the event cards and the map markers all render this, so the
 * symbol an operator learns from the legend is exactly the one on the map.
 * Paths follow Lucide's 24px line style (lucide.dev, ISC licence).
 */

import type { HazardKind } from '../types/events'

const PATHS: Record<HazardKind, string[]> = {
  fire: [
    'M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5z',
  ],
  air_pollution: [
    'M4 14.9A7 7 0 1 1 15.7 8h1.8a4.5 4.5 0 0 1 2.5 8.24',
    'M16 17H7',
    'M17 21H9',
  ],
  flood: [
    'M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1',
    'M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1',
    'M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1',
  ],
  earthquake: ['M2 12h4l3-9 6 18 3-9h4'],
  other: [
    'M21.73 18l-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3',
    'M12 9v4',
    'M12 17h.01',
  ],
}

function HazardIcon({ kind }: { kind: HazardKind }) {
  return (
    <svg
      className="hazard-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[kind].map((d) => <path key={d} d={d} />)}
    </svg>
  )
}

export default HazardIcon
