/**
 * WhatToSeeControl — the "I want to see" bar above the map.
 *
 * Separate from LayersControl on purpose. LayersControl floats over the map and
 * switches environmental overlays on and off — weather, danger, wind. This bar
 * is for the fixed things on the ground: infrastructure that is where it is
 * regardless of the weather.
 *
 * Each toggle carries the service's own emblem, the same badge the map draws,
 * so the bar is also the legend and the map needs no second panel to explain
 * its markers.
 */

import '../pages/visuals/whattoseecontrol.css'


export type SeeToggle = {
  /** Stable key, also used as the React key. */
  id: string

  /** Label shown in the chip. Plain words — no emoji. */
  label: string

  checked: boolean
  onToggle: () => void

  /**
   * The service emblem and its ring colour, matching the badge the map draws.
   * Passed rather than looked up here so each service's appearance is declared
   * once, by the dashboard that mounts both the chip and the layer.
   */
  swatch?: { logo: string; ring: string }

  /**
   * Shown after the label once the layer is on, e.g. "105 of 115". Lets the bar
   * admit that some stations have no coordinates instead of letting the map
   * imply the list is complete.
   */
  note?: string | null
}


type WhatToSeeControlProps = {
  toggles: SeeToggle[]
}


function WhatToSeeControl({ toggles }: WhatToSeeControlProps) {
  return (
    <div className="see-bar">
      <span className="see-bar__title">I want to see</span>

      {toggles.map((toggle) => (
        <label
          key={toggle.id}
          className={`see-chip ${toggle.checked ? 'see-chip--on' : ''}`}
        >
          <input
            type="checkbox"
            className="see-chip__input"
            checked={toggle.checked}
            onChange={toggle.onToggle}
          />

          {toggle.swatch && (
            <span
              className="see-chip__swatch"
              style={{ boxShadow: `0 0 0 1.5px ${toggle.swatch.ring}` }}
            >
              <img src={toggle.swatch.logo} alt="" aria-hidden="true" />
            </span>
          )}

          <span>{toggle.label}</span>

          {toggle.checked && toggle.note && (
            <span className="see-chip__note">{toggle.note}</span>
          )}
        </label>
      ))}
    </div>
  )
}


export default WhatToSeeControl
