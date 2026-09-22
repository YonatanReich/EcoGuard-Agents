/**
 * Home page — the landing and "log in" screen at /.
 *
 * Responsible for introducing the product and sending the user through to
 * the dashboard. There is no real authentication yet: the button is a
 * navigation trigger, not a credential check.
 *
 * The bot arrives with its shield already coated blue over the tree art; the
 * service area outline then traces onto it and fills green.
 * Styling comes from the global index.css (the .home__* classes).
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

// Same outline IsraelMask punches out of the dashboard map, so the two agree.
import serviceAreaText from '../../../data/reference/ecoguard_service_area.geojson?raw'

type Position = [number, number]

/**
 * The shield's inner face (inside the rim) in logo-bot.png's own 500×500
 * pixel space, traced by eye. Redraw it if the image ever changes.
 */
const SHIELD_FACE =
  '100,194 115,180 128,167 167,163 210,167 227,177 243,193 253,207 254,240 ' +
  '255,280 253,307 243,330 227,357 207,383 170,403 153,393 128,373 107,340 ' +
  '97.5,312 97,280 98,240 99.5,203'

const ring: Position[] = JSON.parse(serviceAreaText).features[0].geometry.coordinates[0]
const lons = ring.map(([lon]) => lon)
const lats = ring.map(([, lat]) => lat)
const midLon = (Math.min(...lons) + Math.max(...lons)) / 2
const midLat = (Math.min(...lats) + Math.max(...lats)) / 2
const maxLat = Math.max(...lats)

const SCALE = 222 / (maxLat - Math.min(...lats)) // outline height on the shield, image px
const COS = Math.cos((31.5 * Math.PI) / 180)     // ponytail: equirectangular at Israel's mid-latitude
const TILT = Math.tan((5 * Math.PI) / 180)       // the shield's top edge drops ~5° to the right

/** lon/lat → shield pixel, centred on the face and sheared to its tilt. */
function onShield([lon, lat]: Position): Position {
  const u = (lon - midLon) * COS * SCALE
  return [172 + u, 284 + (midLat - lat) * SCALE + u * TILT]
}

// Start the trace at the northernmost vertex so the outline draws from the top.
const north = lats.indexOf(maxLat)
const OUTLINE =
  'M' +
  [...ring.slice(north), ...ring.slice(0, north)]
    .map((p) => onShield(p).map((n) => n.toFixed(1)).join(','))
    .join('L') +
  'Z'

function Home() {
  const navigate = useNavigate()

  /**
   * True once the user has clicked through, which adds the .home--leaving
   * class and starts the exit animation. Kept in state purely to drive CSS.
   */
  const [leaving, setLeaving] = useState(false)

  /**
   * The entrance waits for the whole page (window load and web fonts) and for
   * the bot image itself (or its failure), so nothing starts half-painted and
   * the coat never floats on its own. Both are needed: React can mount the
   * image after window load has already fired.
   */
  const [pageLoaded, setPageLoaded] = useState(false)
  const [botLoaded, setBotLoaded] = useState(false)

  useEffect(() => {
    const onLoad = () => document.fonts.ready.then(() => setPageLoaded(true))
    if (document.readyState === 'complete') {
      onLoad()
      return
    }
    window.addEventListener('load', onLoad, { once: true })
    return () => window.removeEventListener('load', onLoad)
  }, [])

  /**
   * Play the exit animation, then navigate.
   *
   * The 700ms delay must stay in step with the .home--leaving animations in
   * index.css — navigating sooner would unmount the page mid-animation.
   */
  const leaveTo = (path: string) => {
    setLeaving(true)
    setTimeout(() => navigate(path), 700)
  }

  return (
    <main className={`home${pageLoaded && botLoaded ? ' home--ready' : ''}${leaving ? ' home--leaving' : ''}`}>
      <div className="home__intro">
        <h1 className="home__title">
          <span className="home__eco">
            <svg className="home__leaf" viewBox="0 0 32 32" aria-hidden="true">
              <path d="M5 27C5 13 13 5 28 4c-1 15-9 23-23 23z" />
              <path d="M5 27 19 13" className="home__leaf-vein" />
            </svg>
            Eco
          </span>Guard Agents
        </h1>
        <p className="home__subtitle">
          Your Agentic dream team for Eco Crisis management.
        </p>
        <div className="home__actions">
          <button className="login-button" onClick={() => leaveTo('/dashboard')}>
            Log in
          </button>
          <button className="demo-button" onClick={() => leaveTo('/demo')}>
            View demo
          </button>
        </div>
      </div>

      <div className="home__stage" aria-hidden="true">
        <img
          src="/logo-bot.png"
          alt=""
          onLoad={() => setBotLoaded(true)}
          onError={() => setBotLoaded(true)}
        />
        <svg viewBox="0 0 500 500">
          <defs>
            <linearGradient id="shield-coat" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#0a7cc0" />
              <stop offset="1" stopColor="#005893" />
            </linearGradient>
          </defs>
          <polygon className="home__coat" points={SHIELD_FACE} />
          <path className="home__outline" d={OUTLINE} pathLength={1} />
        </svg>
      </div>
    </main>
  )
}

export default Home

// Vercel frontend merge test
