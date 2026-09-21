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
const BAND_COLOR: Record<WaterLevelBand, { text: string; bg: string; border: string }> = {
  above_upper_red: { text: '#92400e', bg: 'rgba(255,251,235,.97)', border: '#fcd34d' },
  normal: { text: '#166534', bg: 'rgba(240,253,244,.97)', border: '#86efac' },
  below_lower_red: { text: '#9a3412', bg: 'rgba(255,247,237,.97)', border: '#fdba74' },
  below_black: { text: '#7f1d1d', bg: 'rgba(254,242,242,.97)', border: '#fca5a5' },
}

function KinneretLevelCard() {
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

  return <Advisory advisory={data.advisory} stale={failed} />
}

function Advisory({ advisory, stale }: { advisory: KinneretAdvisory; stale: boolean }) {
  const palette = BAND_COLOR[advisory.band]
  const below = advisory.distance_to_lower_red_m
  return (
    <div
      style={{
        ...containerStyle,
        color: palette.text,
        background: palette.bg,
        borderColor: palette.border,
      }}
    >
      <div style={headerStyle}>
        <strong>Kinneret</strong>
        <span style={levelStyle}>{advisory.level_m.toFixed(2)} m</span>
      </div>

      <div style={bandStyle}>{BAND_LABEL[advisory.band]}</div>

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

const containerStyle: CSSProperties = { margin: '0 0 10px', padding: '10px 12px', borderRadius: 9,
  border: '1px solid', fontSize: '.82rem' }
const headerStyle: CSSProperties = { display: 'flex', alignItems: 'baseline',
  justifyContent: 'space-between', gap: 8 }
const levelStyle: CSSProperties = { fontWeight: 700, fontSize: '.95rem' }
const bandStyle: CSSProperties = { marginTop: 3, fontWeight: 700, fontSize: '.76rem',
  textTransform: 'uppercase', letterSpacing: '.02em' }
const detailStyle: CSSProperties = { marginTop: 3, fontWeight: 600 }
const actionStyle: CSSProperties = { marginTop: 7, paddingTop: 7, borderTop: '1px solid currentColor',
  opacity: .92, fontWeight: 600 }
const noteStyle: CSSProperties = { marginTop: 5, opacity: .78, fontSize: '.72rem' }
const mutedStyle: CSSProperties = { margin: '0 0 10px', padding: '8px 12px', borderRadius: 9,
  background: 'rgba(148,163,184,.12)', color: '#475569', fontSize: '.78rem' }

export default KinneretLevelCard
