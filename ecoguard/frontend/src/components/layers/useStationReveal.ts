/**
 * Reveal and dismiss a station layer, instead of switching it.
 *
 * Switching a layer on drops several hundred badges onto the map in one frame,
 * which reads as a glitch rather than as data arriving. Instead a horizontal
 * line sweeps down the country and stations light up as it passes them, and
 * switching off fades the whole layer rather than blinking it away.
 *
 * The sweep is a paint expression, not a per-feature loop: `icon-opacity` reads
 * each station's own latitude and compares it with a line this hook moves each
 * frame, so the work stays on the GPU however many stations there are.
 *
 * Requires every feature to carry a numeric `lat` property — see withLatitude.
 */

import { useEffect, useRef, useState } from 'react'

const SWEEP_MS = 900
const FADE_MS = 380
/** Degrees of latitude over which a station fades up as the line passes. */
const BAND = 0.55

/** Israel, north to south, with room for the band to start fully off screen. */
const NORTH = 33.4
const SOUTH = 29.4


export type RevealState = {
  /** Whether the layer should be in the tree at all. */
  mounted: boolean
  /** Expression for icon-opacity, already combined with any per-feature dimming. */
  opacity: any
}


/**
 * Add a `lat` property to each feature, so the sweep expression can read it.
 *
 * Mapbox expressions cannot get at a feature's geometry, only its properties.
 */
export function withLatitude<T extends GeoJSON.FeatureCollection>(collection: T): T {
  return {
    ...collection,
    features: collection.features.map((feature) => {
      const geometry = feature.geometry
      if (!geometry || geometry.type !== 'Point') return feature
      return {
        ...feature,
        properties: { ...feature.properties, lat: geometry.coordinates[1] },
      }
    }),
  }
}


/**
 * @param visible  what the checkbox says
 * @param dim      per-feature opacity expression, or a constant, applied
 *                 underneath the reveal — this is how an approximate station
 *                 stays faded once it has been revealed
 */
export function useStationReveal(visible: boolean, dim: any = 1): RevealState {
  const [mounted, setMounted] = useState(visible)
  const [progress, setProgress] = useState(visible ? 1 : 0)
  const [mode, setMode] = useState<'sweep' | 'fade'>('sweep')
  const frame = useRef<number | null>(null)

  useEffect(() => {
    const stop = () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current)
      frame.current = null
    }
    stop()

    const started = performance.now()

    if (visible) {
      setMounted(true)
      setMode('sweep')
      const from = progress
      const run = (now: number) => {
        // Resuming from wherever a cancelled fade left off, so toggling twice
        // quickly does not restart the sweep from an empty map.
        const t = Math.min(1, from + (now - started) / SWEEP_MS)
        setProgress(t)
        if (t < 1) frame.current = requestAnimationFrame(run)
      }
      frame.current = requestAnimationFrame(run)
    } else {
      setMode('fade')
      const from = progress
      const run = (now: number) => {
        const t = Math.max(0, from - (now - started) / FADE_MS)
        setProgress(t)
        if (t > 0) frame.current = requestAnimationFrame(run)
        else setMounted(false)
      }
      frame.current = requestAnimationFrame(run)
    }

    return stop
    // progress is deliberately not a dependency: it changes every frame, and
    // reading it here is only to pick up where the previous run stopped.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible])

  let opacity: any
  if (mode === 'fade') {
    // Whole layer dims together on the way out. A reverse sweep would look like
    // the data was being taken away one region at a time.
    opacity = ['*', dim, progress]
  } else {
    // The line starts north of everything and ends south of it, so the first
    // frame shows nothing and the last shows all of them.
    const line = NORTH + BAND - progress * (NORTH - SOUTH + BAND * 2)
    opacity = ['*', dim, [
      'interpolate', ['linear'], ['get', 'lat'],
      line, 0,
      line + BAND, 1,
    ]]
  }

  return { mounted, opacity }
}
