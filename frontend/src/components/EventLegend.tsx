/**
 * EventLegend — how to read the map and the cards.
 *
 * Colour means hazard type; the panel an event sits in means urgency. Those
 * are two independent axes and the legend says so, because a reader who
 * assumes red-is-urgent will misread an orange advisory fire.
 */

import { HAZARDS, CLASSIFICATION_IS_INFERRED, type HazardKind } from './hazards'

const ORDER: HazardKind[] = ['fire', 'air_pollution', 'flood', 'other']


function EventLegend({ emergencyCount, advisoryCount }: {
  emergencyCount: number
  advisoryCount: number
}) {
  return (
    <section className="legend" aria-label="Map and card legend">

      <div className="legend__group">
        <span className="legend__caption">Hazard</span>
        {ORDER.map((kind) => (
          <span key={kind} className="legend__item">
            <span
              className="legend__swatch"
              style={{ background: HAZARDS[kind].color }}
            />
            {HAZARDS[kind].label}
          </span>
        ))}
      </div>

      <div className="legend__group">
        <span className="legend__caption">Urgency</span>
        <span className="legend__item">
          <span className="legend__pulse" />
          Emergency — right panel, pulsing on the map
          <strong className="legend__count">{emergencyCount}</strong>
        </span>
        <span className="legend__item">
          <span className="legend__dot" />
          Advisory — left panel, steady dot
          <strong className="legend__count">{advisoryCount}</strong>
        </span>
      </div>

      {CLASSIFICATION_IS_INFERRED && (
        <p className="legend__note">
          Urgency is currently inferred from the risk band. The triage stage
          will set it from severity, population proximity and actionability.
        </p>
      )}

    </section>
  )
}

export default EventLegend
