/**
 * KinneretLayer — the lake itself, as a clickable object on the map.
 *
 * The outline is OpenStreetMap relation 8630890 (ODbL), fetched once and
 * committed to public/kinneret.geojson rather than queried at run time: the
 * shoreline moves with the water level by metres, not by anything a map at
 * this zoom can show, so a live fetch would buy nothing and add a dependency.
 *
 * Hovering lights it blue; clicking opens the advisory card that the sidebar
 * already renders, so the popup and the panel can never disagree.
 *
 * Every paint here is emissive: Standard's dusk lighting otherwise shades
 * added layers down, which is what kept the old hover glow nearly invisible.
 */

import { useEffect, useState } from 'react'
import { Layer, Popup, Source, useMap } from 'react-map-gl/mapbox'
import type { MapLayerMouseEvent } from 'mapbox-gl'

import KinneretLevelCard from '../KinneretLevelCard'

const SOURCE_ID = 'kinneret'
const FILL_LAYER_ID = 'kinneret-fill'
const HOVER_FADE_MS = 200

function KinneretLayer() {
  const { current: map } = useMap()
  const [hovered, setHovered] = useState(false)
  const [popupAt, setPopupAt] = useState<{ lng: number; lat: number } | null>(null)

  useEffect(() => {
    if (!map) return

    // ponytail: one feature, so plain state beats feature-state — there is
    // nothing to tell apart. Swap to feature-state only if more water bodies
    // join this source.
    const onEnter = () => {
      setHovered(true)
      map.getCanvas().style.cursor = 'pointer'
    }
    const onLeave = () => {
      setHovered(false)
      map.getCanvas().style.cursor = ''
    }
    const onClick = (event: MapLayerMouseEvent) => {
      setPopupAt({ lng: event.lngLat.lng, lat: event.lngLat.lat })
    }

    map.on('mouseenter', FILL_LAYER_ID, onEnter)
    map.on('mouseleave', FILL_LAYER_ID, onLeave)
    map.on('click', FILL_LAYER_ID, onClick)

    return () => {
      map.off('mouseenter', FILL_LAYER_ID, onEnter)
      map.off('mouseleave', FILL_LAYER_ID, onLeave)
      map.off('click', FILL_LAYER_ID, onClick)
      if (map.getCanvas()) map.getCanvas().style.cursor = ''
    }
  }, [map])

  return (
    <>
      <Source id={SOURCE_ID} type="geojson" data="/kinneret.geojson">
        {/* Drawn first so the blur spills underneath the crisp edge. */}
        <Layer
          id="kinneret-glow"
          type="line"
          paint={{
            'line-color': '#3b82f6',
            'line-width': 18,
            'line-blur': 12,
            'line-opacity': hovered ? 0.95 : 0,
            'line-opacity-transition': { duration: HOVER_FADE_MS },
            'line-emissive-strength': 1,
          }}
        />

        <Layer
          id={FILL_LAYER_ID}
          type="fill"
          paint={{
            'fill-color': '#3b82f6',
            'fill-opacity': hovered ? 0.4 : 0.14,
            'fill-opacity-transition': { duration: HOVER_FADE_MS },
            'fill-emissive-strength': 1,
          }}
        />

        <Layer
          id="kinneret-outline"
          type="line"
          paint={{
            'line-color': hovered ? '#bfdbfe' : '#60a5fa',
            'line-color-transition': { duration: HOVER_FADE_MS },
            'line-width': hovered ? 2.6 : 1.4,
            'line-width-transition': { duration: HOVER_FADE_MS },
            'line-opacity': 0.95,
            'line-emissive-strength': 1,
          }}
        />
      </Source>

      {popupAt && (
        <Popup
          longitude={popupAt.lng}
          latitude={popupAt.lat}
          anchor="bottom"
          offset={10}
          maxWidth="260px"
          // The card is the whole popup; a click anywhere else on the map
          // closes it, so it needs no close button eating into its header.
          closeButton={false}
          className="kinneret-popup"
          onClose={() => setPopupAt(null)}
        >
          <KinneretLevelCard compact />
        </Popup>
      )}
    </>
  )
}

export default KinneretLayer
