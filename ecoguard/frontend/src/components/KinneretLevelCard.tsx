import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import type {
  KinneretAdvisory,
  WaterLevelBand,
  WaterLevelResponse,
} from '../types/events'

// The lake moves by centimetres a day and the collector polls every six
// hours, so this refreshes on a slow timer rather than with the event feed.
const REFRESH_MS = 30 * 60 * 1000

const BAND_LABEL: Record<WaterLevelBand, string> = {
  above_upper_red: 'Above upper red line',
  normal: 'Within operating range',
  below_lower_red: 'Below lower red line',
  below_black: 'Below black line',
}

// Amber for the overflow case rather than green: it is not an emergency, but
// it is not "nothing to do" either — the dam has to be opened.
// On the dark dashboard the band colour is an accent (edge, level, band name)
// over a faint tint of itself, not a light card of its own.
const BAND_COLOR: Record<WaterLevelBand, { text: string; bg: string; border: string }> = {
  above_upper_red: { text: '#fcd34d', bg: 'rgba(252,211,77,.06)', border: 'rgba(252,211,77,.28)' },
  normal: { text: '#86efac', bg: 'rgba(134,239,172,.06)', border: 'rgba(134,239,172,.28)' },
  below_lower_red: { text: '#fdba74', bg: 'rgba(253,186,116,.06)', border: 'rgba(253,186,116,.28)' },
  below_black: { text: '#fca5a5', bg: 'rgba(252,165,165,.07)', border: 'rgba(252,165,165,.3)' },
}

function KinneretLevelCard({ compact = false }: {
  /** The map popup's version: no outer margin, tighter type and padding. */
  compact?: boolean
}) {
  const [data, setData] = useState<WaterLevelResponse | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const response = await fetch('/api/water-levels')
        if (!response.ok) throw new Error(String(response.status))
        const body: WaterLevelResponse = await response.json()
        if (!cancelled) {
          setData(body)
          setFailed(false)
        }
      } catch {
        // Keep the last good reading on screen rather than blanking it; a
        // stale lake level is still roughly right, and a card that vanishes
        // on one failed poll reads as "no advisory".
        if (!cancelled) setFailed(true)
      }
    }

    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  if (data === null) {
    return failed ? <div style={mutedStyle}>Kinneret level unavailable.</div> : null
  }
  if (data.status === 'unavailable') {
    return <div style={mutedStyle}>Kinneret level not collected yet.</div>
  }

  return <Advisory advisory={data.advisory} stale={failed} compact={compact} />
}

function Advisory({ advisory, stale, compact }: { advisory: KinneretAdvisory; stale: boolean; compact: boolean }) {
  const palette = BAND_COLOR[advisory.band]
  const below = advisory.distance_to_lower_red_m
  return (
    <div
      style={{
        ...containerStyle,
        ...(compact && { margin: 0, padding: '8px 10px', fontSize: '.76rem' }),
        background: palette.bg,
        borderColor: palette.border,
        borderLeftColor: palette.text,
      }}
    >
      <div style={headerStyle}>
        <strong>Kinneret</strong>
        <span style={{ ...levelStyle, color: palette.text }}>{advisory.level_m.toFixed(2)} m</span>
      </div>

      <div style={{ ...bandStyle, color: palette.text }}>{BAND_LABEL[advisory.band]}</div>

      <div style={detailStyle}>
        {below > 0
          ? `${below.toFixed(2)} m below the lower red line`
          : `${Math.abs(below).toFixed(2)} m above the lower red line`}
      </div>

      <div style={detailStyle}>
        {advisory.trend_m_per_year === null
          ? 'Trend not assessed'
          : `${advisory.trend_m_per_year < 0 ? 'Falling' : 'Rising'} ${Math.abs(
              advisory.trend_m_per_year,
            ).toFixed(2)} m/year`}
        {advisory.days_to_black_line !== null &&
          ` · black line in ~${advisory.days_to_black_line} days`}
      </div>

      <div style={actionStyle}>{advisory.action}</div>

      <div style={noteStyle}>
        Water Authority operating lines · surveyed{' '}
        {new Date(advisory.observed_at).toLocaleDateString()}
        {stale && ' · refresh failed'}
      </div>
    </div>
  )
}

const containerStyle: CSSProperties = { margin: '0 0 10px', padding: '10px 12px', borderRadius: 8,
  border: '1px solid', borderLeftWidth: 3, color: '#d5deea', fontSize: '.82rem' }
const headerStyle: CSSProperties = { display: 'flex', alignItems: 'baseline',
  justifyContent: 'space-between', gap: 8 }
const levelStyle: CSSProperties = { fontWeight: 700, fontSize: '.95rem', fontVariantNumeric: 'tabular-nums' }
const bandStyle: CSSProperties = { marginTop: 2, fontWeight: 700, fontSize: '.78rem' }
const detailStyle: CSSProperties = { marginTop: 3, color: '#aab6c8' }
const actionStyle: CSSProperties = { marginTop: 8, paddingTop: 8,
  borderTop: '1px solid rgba(148,170,200,.14)', fontWeight: 600 }
const noteStyle: CSSProperties = { marginTop: 6, color: '#6b788d', fontSize: '.72rem' }
const mutedStyle: CSSProperties = { margin: '0 0 10px', padding: '8px 12px', borderRadius: 8,
  background: 'rgba(148,170,200,.06)', color: '#8594ab', fontSize: '.78rem' }

export default KinneretLevelCard
