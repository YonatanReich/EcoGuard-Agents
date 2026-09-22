import type { CSSProperties } from 'react'

const SEVERITY_LEVELS = [
  { label: '10-year', color: '#facc15' },
  { label: '20-year', color: '#f97316' },
  { label: '50-year', color: '#ef4444' },
  { label: '100-year', color: '#7f1d1d' },
]

// Closed by default: a chip on the map until the operator asks for the key.
// A native <details>, so opening it is a click or Enter with nothing to wire.
function FloodLegend() {
  return (
    <details className="flood-legend" style={containerStyle} aria-label="Flood map legend">
      <summary className="flood-legend__summary">Flood response</summary>

      {SEVERITY_LEVELS.map((level) => (
        <div key={level.label} style={rowStyle}>
          <span
            style={{
              ...streamLineStyle,
              borderColor: level.color,
              boxShadow: `0 0 0 3px ${level.color}33`,
            }}
          />
          <span style={labelStyle}>Stream warning</span>
          <span style={rangeStyle}>{level.label}</span>
        </div>
      ))}

      <div style={dividerStyle} />

      <div style={rowStyle}>
        <span style={stationStyle}>≋</span>
        <span style={labelStyle}>Hydrometric station</span>
      </div>
      <div style={rowStyle}>
        <span style={crossingStyle}>×</span>
        <span style={labelStyle}>Road response site</span>
      </div>
      <div style={rowStyle}>
        <span style={accessStyle} />
        <span style={labelStyle}>Verified vehicle access</span>
      </div>
      <div style={rowStyle}>
        <span style={uncertaintyStyle} />
        <span style={labelStyle}>Station-location uncertainty</span>
      </div>

      <div style={noteStyle}>Stream line is not an inundation boundary.</div>
    </details>
  )
}

const containerStyle: CSSProperties = {
  position: 'absolute',
  bottom: 36,
  left: 12,
  zIndex: 5,
  padding: '8px 12px',
  borderRadius: 8,
  border: '1px solid rgba(148, 170, 200, 0.16)',
  background: 'rgba(8, 14, 26, 0.93)',
  color: '#e4ebf5',
  boxShadow: '0 8px 24px rgba(0, 0, 0, 0.4)',
  fontSize: '0.8rem',
}

const rowStyle: CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, marginTop: 5 }
const labelStyle: CSSProperties = { flex: 1 }
const rangeStyle: CSSProperties = { color: '#8594ab', fontSize: '0.72rem' }
const streamLineStyle: CSSProperties = { width: 22, height: 0, borderTop: '4px solid', flexShrink: 0 }
const dividerStyle: CSSProperties = { borderTop: '1px solid rgba(148, 170, 200, 0.16)', margin: '9px 0 4px' }
const stationStyle: CSSProperties = {
  display: 'grid', placeItems: 'center', width: 18, height: 18,
  borderRadius: '50%', background: '#ef4444', color: '#fff', fontWeight: 800,
}
const crossingStyle: CSSProperties = {
  display: 'grid', placeItems: 'center', width: 18, height: 18,
  borderRadius: 3, background: '#b91c1c', color: '#fff', fontWeight: 900,
}
const accessStyle: CSSProperties = {
  width: 12, height: 12, margin: 3, border: '2px solid #fff',
  borderRadius: '50%', background: '#38bdf8', boxShadow: '0 0 0 1px #64748b',
}
const uncertaintyStyle: CSSProperties = {
  width: 17, height: 17, border: '2px dashed #f97316', borderRadius: '50%',
}
const noteStyle: CSSProperties = {
  marginTop: 9, paddingTop: 7, borderTop: '1px solid rgba(148, 170, 200, 0.16)',
  color: '#8594ab', fontSize: '0.68rem',
}

export default FloodLegend
