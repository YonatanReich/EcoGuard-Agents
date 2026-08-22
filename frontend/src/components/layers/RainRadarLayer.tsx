/**
 * RainRadarLayer
 *
 * Displays RainViewer precipitation radar frames as a raster overlay on top
 * of the existing MapLibre / MapTiler map.
 *
 * The component fetches RainViewer metadata once, stores the available recent
 * radar frames locally, and then switches between them without performing a
 * new metadata request for every timeline change.
 *
 * This layer is visualization-only and is not part of the backend risk
 * analysis pipeline.
 */

import {
  useEffect,
  useMemo,
  useState,
} from 'react'

import {
  Layer,
  Source,
} from 'react-map-gl/maplibre'


export type RainViewerFrame = {
  time: number
  path: string
}


type RainViewerResponse = {
  version: string
  host: string

  radar?: {
    past?: RainViewerFrame[]
    nowcast?: RainViewerFrame[]
  }
}


type RainRadarLayerProps = {
  /** Opacity of the radar overlay. */
  opacity?: number

  /** Whether the radar layer should be rendered. */
  visible?: boolean

  /**
   * Index of the selected radar frame.
   *
   * 0 represents the oldest available frame.
   * The highest index represents the most recent frame.
   */
  selectedFrameIndex?: number

  /**
   * Reports all available radar frames to the parent.
   */
  onFramesChange?: (
    frames: RainViewerFrame[]
  ) => void

  /**
   * Reports the Unix timestamp of the currently displayed frame.
   */
  onFrameTimeChange?: (
    timestamp: number | null
  ) => void
}


function RainRadarLayer({
  opacity = 0.65,
  visible = true,
  selectedFrameIndex,
  onFramesChange,
  onFrameTimeChange,
}: RainRadarLayerProps) {

  /**
   * RainViewer host returned by the metadata endpoint.
   */
  const [
    host,
    setHost,
  ] =
    useState<string | null>(null)


  /**
   * Available historical radar frames.
   */
  const [
    frames,
    setFrames,
  ] =
    useState<RainViewerFrame[]>([])


  /**
   * Fetch RainViewer metadata once when the component mounts.
   */
  useEffect(() => {
    let cancelled = false

    const loadRadarMetadata =
      async () => {

        try {
          const response =
            await fetch(
              'https://api.rainviewer.com/public/weather-maps.json'
            )

          if (!response.ok) {
            throw new Error(
              `RainViewer metadata request failed with status ${response.status}`
            )
          }

          const data:
            RainViewerResponse =
            await response.json()

          const radarFrames =
            data.radar?.past ??
            []

          if (cancelled) {
            return
          }

          setHost(
            data.host
          )

          setFrames(
            radarFrames
          )

          onFramesChange?.(
            radarFrames
          )
        } catch (
          error
        ) {
          console.error(
            'Failed to load RainViewer radar metadata:',
            error
          )

          if (!cancelled) {
            setHost(null)
            setFrames([])

            onFramesChange?.(
              []
            )

            onFrameTimeChange?.(
              null
            )
          }
        }
      }

    loadRadarMetadata()

    return () => {
      cancelled = true
    }

    /**
     * Metadata is intentionally loaded once.
     */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])


  /**
   * Determine which frame should currently be displayed.
   *
   * If the parent does not provide an index, default to the newest frame.
   */
  const activeFrame =
    useMemo(() => {

      if (
        frames.length === 0
      ) {
        return null
      }

      if (
        selectedFrameIndex ===
          undefined
      ) {
        return (
          frames[
            frames.length - 1
          ]
        )
      }

      const safeIndex =
        Math.max(
          0,
          Math.min(
            selectedFrameIndex,
            frames.length - 1
          )
        )

      return (
        frames[safeIndex]
      )
    }, [
      frames,
      selectedFrameIndex,
    ])


  /**
   * Report the timestamp whenever the active radar frame changes.
   */
  useEffect(() => {
    onFrameTimeChange?.(
      activeFrame?.time ??
      null
    )
  }, [
    activeFrame,
    onFrameTimeChange,
  ])


  /**
   * Build the XYZ radar tile URL for the active frame.
   */
  const tileUrl =
    useMemo(() => {

      if (
        !host ||
        !activeFrame
      ) {
        return null
      }

      return (
        `${host}` +
        `${activeFrame.path}` +
        `/256/{z}/{x}/{y}/2/1_1.png`
      )
    }, [
      host,
      activeFrame,
    ])


  if (
    !visible ||
    !tileUrl
  ) {
    return null
  }


  return (
    <Source
      key={
        activeFrame?.time
      }
      id="rainviewer-radar-source"
      type="raster"
      tiles={[
        tileUrl,
      ]}
      tileSize={256}
      maxzoom={7}
    >
      <Layer
        id="rainviewer-radar-layer"
        type="raster"
        paint={{
          'raster-opacity':
            opacity,

          'raster-fade-duration':
            0,
        }}
      />
    </Source>
  )
}


export default RainRadarLayer