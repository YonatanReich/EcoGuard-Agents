/**
 * LayersControl
 *
 * Map overlay used to enable or disable optional visualization layers.
 *
 * Environmental layers are controlled independently so the operator can
 * combine multiple sources on the same map when needed.
 *
 * Current layers:
 *   - Rain Radar — live precipitation radar from RainViewer.
 *   - Fire Danger — Fire Weather Index (FWI) from GWIS/EFFIS.
 *   - Flood Events — active stream warnings and operational road sites.
 *   - Wind — animated near-surface wind visualization from Open-Meteo.
 *   - Fire Districts — the seven fire & rescue districts of responsibility.
 *   - Allocations — assigned stations and their routes to the selected event.
 *
 * Additional layers can be added here later without changing MapView.
 */

import type { CSSProperties } from 'react'

type LayersControlProps = {
  /** Whether the RainViewer radar overlay is currently visible. */
  showRainRadar: boolean

  /** Toggle the RainViewer radar overlay. */
  onToggleRainRadar: () => void

  /** Whether the GWIS/EFFIS FWI overlay is currently visible. */
  showFireDanger: boolean

  /** Toggle the GWIS/EFFIS FWI overlay. */
  onToggleFireDanger: () => void

  /** Whether the national Current Risk grid is visible. */
  showFireRisk: boolean

  /** Toggle the national Current Risk grid. */
  onToggleFireRisk: () => void

  /** Whether active Flood event geometry and markers are visible. */
  showFloodEvents: boolean

  /** Toggle the active Flood event layer. */
  onToggleFloodEvents: () => void

  /** Whether the animated wind layer is currently visible. */
  showWind: boolean

  /** Toggle the animated wind layer. */
  onToggleWind: () => void

  /** Whether the seven fire & rescue district outlines are visible. */
  showFireDistricts: boolean

  /** Toggle the fire & rescue district outlines. */
  onToggleFireDistricts: () => void

  /** Whether assigned stations and their routes are visible. */
  showAllocations: boolean

  /** Toggle assigned stations and their routes as one operational layer. */
  onToggleAllocations: () => void

}

function LayersControl({
  showRainRadar,
  onToggleRainRadar,
  showFireDanger,
  onToggleFireDanger,
  showFireRisk,
  onToggleFireRisk,
  showFloodEvents,
  onToggleFloodEvents,
  showWind,
  onToggleWind,
  showFireDistricts,
  onToggleFireDistricts,
  showAllocations,
  onToggleAllocations,
}: LayersControlProps) {
  return (
    <div style={containerStyle}>
      <div style={titleStyle}>Map Layers</div>

      <label style={rowStyle}>
        <input
          type="checkbox"
          checked={showFireRisk}
          onChange={onToggleFireRisk}
        />
        <span>Fire Risk</span>
      </label>

      <label style={rowStyle}>
        <input
          type="checkbox"
          checked={showRainRadar}
          onChange={onToggleRainRadar}
        />
        <span>🌧 Rain Radar</span>
      </label>

      <label style={rowStyle}>
        <input
          type="checkbox"
          checked={showFireDanger}
          onChange={onToggleFireDanger}
        />
        <span>🔥 Fire Danger</span>
      </label>

      <label style={rowStyle}>
        <input
          type="checkbox"
          checked={showWind}
          onChange={onToggleWind}
        />
        <span>💨 Wind</span>
      </label>

      <label style={rowStyle}>
        <input
          type="checkbox"
          checked={showFireDistricts}
          onChange={onToggleFireDistricts}
        />
        <span>🛡 Fire Districts</span>
      </label>

      <label style={rowStyle}>
        <input
          type="checkbox"
          checked={showFloodEvents}
          onChange={onToggleFloodEvents}
        />
        <span>🌊 Flood Events</span>
      </label>

      <label style={rowStyle}>
        <input
          type="checkbox"
          checked={showAllocations}
          onChange={onToggleAllocations}
        />
        <span>🚨 Allocations</span>
      </label>

    </div>
  )
}

const containerStyle: CSSProperties = {
  position: 'absolute',
  top: 12,
  left: 12,
  zIndex: 5,
  background: 'rgba(255, 255, 255, 0.95)',
  color: '#111827',
  padding: '10px 12px',
  borderRadius: 8,
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.2)',
  fontSize: '0.9rem',
  minWidth: 190,
}

const titleStyle: CSSProperties = {
  fontWeight: 700,
  marginBottom: 8,
}

const rowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  cursor: 'pointer',
  marginTop: 6,
}

export default LayersControl
