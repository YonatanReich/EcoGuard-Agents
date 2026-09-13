/**
 * Turn a service logo into a map badge.
 *
 * Mapbox symbol layers draw registered raster images, not SVG, so each logo is
 * rasterised once into a circular badge — white disc, coloured ring, logo
 * centred — and handed to the map under a name the layer references.
 *
 * The badge is drawn rather than the bare logo because the three emblems have
 * different aspect ratios and no common silhouette. Composited onto one disc
 * they read as a set at a glance, and the white ground keeps them legible over
 * dark terrain and over the red end of the fire danger surface.
 */

import { useEffect, useState } from 'react'

/** Logical size of the badge, in CSS pixels. */
const BADGE_PX = 40
/** Rasterised at 2x so the badge stays crisp on retina displays. */
const SCALE = 2
/** Fraction of the badge the logo occupies, leaving room for the ring. */
const LOGO_FRACTION = 0.6


async function drawBadge(url: string, ring: string): Promise<ImageData> {
  const image = new Image()
  image.src = url
  // decode() rather than onload: it resolves after the SVG is actually ready to
  // draw, so the first frame cannot rasterise an empty image.
  await image.decode()

  const size = BADGE_PX * SCALE
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const context = canvas.getContext('2d')
  if (!context) throw new Error('no 2d context')

  const centre = size / 2
  const radius = centre - SCALE * 1.5

  context.beginPath()
  context.arc(centre, centre, radius, 0, Math.PI * 2)
  context.fillStyle = '#ffffff'
  context.fill()
  context.lineWidth = SCALE * 2.5
  context.strokeStyle = ring
  context.stroke()

  // Contain rather than cover: the emblems are 1.09, 1.06 and 1.00 to 1, and
  // filling the box would crop whichever is furthest from square.
  const natural = image.naturalWidth / image.naturalHeight || 1
  const box = size * LOGO_FRACTION
  const width = natural >= 1 ? box : box * natural
  const height = natural >= 1 ? box / natural : box
  context.drawImage(image, centre - width / 2, centre - height / 2, width, height)

  return context.getImageData(0, 0, size, size)
}


/**
 * Register a badge with the map, and report when it is ready.
 *
 * The layer must not render before the image exists — Mapbox logs a missing
 * image and draws nothing — so the caller gates on the returned flag.
 */
export function useStationBadge(
  map: { getMap: () => any } | undefined,
  name: string,
  logoUrl: string,
  ringColour: string,
): boolean {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!map) return
    const instance = map.getMap()
    if (instance.hasImage(name)) {
      setReady(true)
      return
    }

    let cancelled = false
    drawBadge(logoUrl, ringColour)
      .then((data) => {
        if (cancelled) return
        // hasImage is re-checked because two layers mounting in the same frame
        // would otherwise both try to add it and the second would throw.
        if (!instance.hasImage(name)) {
          instance.addImage(name, data, { pixelRatio: SCALE })
        }
        setReady(true)
      })
      .catch(() => {
        // A missing badge is a missing layer, not a broken dashboard.
        if (!cancelled) setReady(false)
      })

    return () => {
      cancelled = true
    }
  }, [map, name, logoUrl, ringColour])

  return ready
}


/** Zoom ramp shared by the three station layers, so they stay the same size. */
export const BADGE_SIZE_BY_ZOOM: any = [
  'interpolate', ['linear'], ['zoom'],
  6, 0.34,
  10, 0.55,
  14, 0.85,
]
