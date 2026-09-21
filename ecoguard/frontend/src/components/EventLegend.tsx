/**
 * EventLegend — how to read the map and the cards.
 *
 * The icon and its colour mean hazard type; the pulse rate means urgency —
 * fast for an emergency (right panel), slow for an advisory (left panel).
 * Two independent axes, and the legend keeps them apart, because a reader who
 * assumes red-is-urgent will misread an orange advisory fire.
 */

import type { CSSProperties } from 'react'
import HazardIcon from './HazardIcon'
import { HAZARDS, CLASSIFICATION_IS_INFERRED, type HazardKind } from './hazards'

const ORDER: HazardKind[] = ['fire', 'flood', 'earthquake', 'air_pollution', 'other']

const INFERRED_NOTE =
  'Urgency is currently inferred from the risk band. The triage stage will ' +
  'set it from severity, population proximity and actionability.'


function EventLegend() {
  return (
    <section className="legend" aria-label="Map legend">

      <ul className="legend__group">
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

      <ul
        className="legend__group"
        title={CLASSIFICATION_IS_INFERRED ? INFERRED_NOTE : undefined}
      >
        <li className="legend__item">
          <span className="legend__pulse legend__pulse--fast" />
          Emergency
        </li>
        <li className="legend__item">
          <span className="legend__pulse" />
          Advisory
        </li>
      </ul>

    </section>
  )
}

export default EventLegend
