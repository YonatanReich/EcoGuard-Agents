/**
 * LoadingScreen — the boot cover the dashboard wears on the way in.
 *
 * Responsible for holding the entrance until the map has painted and the event
 * feed has answered, so the operator never lands on a half-drawn map with both
 * panels reading "Scanning…". It continues the landing page's exit rather than
 * starting something new: same dark background, opaque from the first frame, so
 * "Monitor" reads as one movement into the system.
 *
 * The animation is the service area outline — the same one IsraelMask punches
 * out of the map — drawing and erasing itself on a loop.
 * Styling comes from the global index.css (the .boot__* classes).
 */

import serviceAreaText from '../../../data/reference/ecoguard_service_area.geojson?raw'

type Position = [number, number]

const ring: Position[] = JSON.parse(serviceAreaText).features[0].geometry.coordinates[0]

// ponytail: equirectangular at Israel's mid-latitude. The shape only has to
// read as the country at logo size; swap in a real projection if it ever has to
// line up against something else.
const COS = Math.cos((31.5 * Math.PI) / 180)

const xs = ring.map(([lon]) => lon * COS)
const ys = ring.map(([, lat]) => -lat)
const minX = Math.min(...xs)
const minY = Math.min(...ys)
const WIDTH = Math.max(...xs) - minX
const HEIGHT = Math.max(...ys) - minY

const OUTLINE =
  'M' +
  ring
    .map(([lon, lat]) => `${(lon * COS - minX).toFixed(4)},${(-lat - minY).toFixed(4)}`)
    .join('L') +
  'Z'

/** `done` starts the fade out; the caller unmounts once it has finished. */
function LoadingScreen({ done }: { done: boolean }) {
  return (
    <div className={`boot${done ? ' boot--done' : ''}`} role="status">
      <svg
        className="boot__map"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        aria-hidden="true"
      >
        <path
          className="boot__outline"
          d={OUTLINE}
          pathLength={1}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <p className="boot__label">Loading system</p>
    </div>
  )
}

export default LoadingScreen
