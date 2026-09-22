/**
 * EventLegend — which icon is which hazard.
 *
 * The same glyph and colour the map markers and event cards use, so the
 * legend is the key to both.
 */

import type { CSSProperties } from 'react'
import HazardIcon from './HazardIcon'
import { HAZARDS, type HazardKind } from './hazards'

const ORDER: HazardKind[] = ['fire', 'flood', 'earthquake', 'air_pollution']


function EventLegend() {
  return (
    <ul className="legend" aria-label="Map legend">
      {ORDER.map((kind) => (
        <li
          key={kind}
          className="legend__item"
          style={{ '--hazard': HAZARDS[kind].color } as CSSProperties}
        >
          <span className="legend__glyph"><HazardIcon kind={kind} /></span>
          {HAZARDS[kind].label}
        </li>
      ))}
    </ul>
  )
}

export default EventLegend
