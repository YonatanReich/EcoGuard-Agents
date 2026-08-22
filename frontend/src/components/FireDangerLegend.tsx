/**
 * FireDangerLegend
 *
 * Displays the official GWIS/EFFIS Fire Weather Index (FWI)
 * danger categories used by the FireDangerLayer.
 *
 * The legend is presentation-only and should be shown only while
 * the Fire Danger map layer is enabled.
 */

import type { CSSProperties } from 'react'

const FWI_LEVELS = [
  {
    label: 'Low',
    range: '< 11.2',
    color: 'rgb(156, 255, 192)',
  },
  {
    label: 'Moderate',
    range: '11.2 – 21.3',
    color: 'rgb(205, 226, 78)',
  },
  {
    label: 'High',
    range: '21.3 – 38',
    color: 'rgb(230, 172, 0)',
  },
  {
    label: 'Very High',
    range: '38 – 50',
    color: 'rgb(217, 112, 16)',
  },
  {
    label: 'Extreme',
    range: '50 – 70',
    color: 'rgb(173, 6, 14)',
  },
  {
    label: 'Very Extreme',
    range: '> 70',
    color: 'rgb(58, 0, 21)',
  },
]

function FireDangerLegend() {
  return (
    <div style={containerStyle}>
      <div style={titleStyle}>
        Fire Danger (FWI)
      </div>

      {FWI_LEVELS.map((level) => (
        <div
          key={level.label}
          style={rowStyle}
        >
          <div
            style={{
              ...colorBoxStyle,
              background: level.color,
            }}
          />

          <div style={labelStyle}>
            {level.label}
          </div>

          <div style={rangeStyle}>
            {level.range}
          </div>
        </div>
      ))}
    </div>
  )
}

const containerStyle: CSSProperties = {
  position: 'absolute',
  bottom: 36,
  left: 12,
  zIndex: 5,
  background: 'rgba(255, 255, 255, 0.95)',
  color: '#111827',
  padding: '10px 12px',
  borderRadius: 8,
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.2)',
  fontSize: '0.8rem',
  minWidth: 180,
}

const titleStyle: CSSProperties = {
  fontWeight: 700,
  marginBottom: 8,
}

const rowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  marginTop: 5,
}

const colorBoxStyle: CSSProperties = {
  width: 18,
  height: 12,
  borderRadius: 2,
  border: '1px solid rgba(0,0,0,0.15)',
  flexShrink: 0,
}

const labelStyle: CSSProperties = {
  flex: 1,
}

const rangeStyle: CSSProperties = {
  color: '#4b5563',
  fontSize: '0.75rem',
}

export default FireDangerLegend