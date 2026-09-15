/**
 * WindParticleLayer
 *
 * Displays animated near-surface wind flow over Israel.
 *
 * Wind observations are fetched once from Open-Meteo for a grid of
 * coordinates covering Israel and its immediate surroundings.
 *
 * The API response includes both recent history and forecast hours.
 * Moving the timeline slider does NOT trigger another network request.
 * Instead, the component reuses the already downloaded hourly dataset
 * and rebuilds the wind texture locally for the selected time.
 *
 * This layer is visualization-only. It does not currently affect the
 * backend RiskAnalysisAgent.
 */

import {
  useEffect,
  useMemo,
  useState,
} from 'react'

import { useControl } from 'react-map-gl/mapbox'
import { MapboxOverlay } from '@deck.gl/mapbox'

import {
  WindParticleLayer as DeckWindParticleLayer,
  generateWindTexture,
} from 'maplibre-gl-wind'


type WindDataPoint = {
  lat: number
  lon: number
  speed: number
  direction: number
}


type OpenMeteoWindResponse = {
  latitude: number
  longitude: number

  current?: {
    time?: number
  }

  hourly?: {
    time?: number[]
    wind_speed_10m?: number[]
    wind_direction_10m?: number[]
  }
}


type WindParticleLayerProps = {
  /**
   * Selected time relative to the current hour.
   *
   * Examples:
   * -6 = six hours ago
   *  0 = current conditions
   * +6 = six-hour forecast
   */
  timeOffsetHours?: number

  /**
   * Reports the actual Unix timestamp selected from Open-Meteo.
   */
  onTimeChange?: (
    timestamp: number | null
  ) => void
}


type DeckOverlayProps = {
  layers: any[]
}


function DeckOverlay({
  layers,
}: DeckOverlayProps) {
  const overlay = useControl<MapboxOverlay>(
    () =>
      new MapboxOverlay({
        interleaved: false,
        layers,
      })
  )

  overlay.setProps({
    layers,
  })

  return null
}


// Geographic area used for the wind texture.
//
// [west, south, east, north]
const WIND_BOUNDS: [
  number,
  number,
  number,
  number
] = [
  33.5,
  29.0,
  36.5,
  33.6,
]


/**
 * Build a coordinate grid over Israel.
 *
 * Open-Meteo returns weather information for every point.
 * generateWindTexture later interpolates between those points.
 */
function buildIsraelWindGrid() {
  const points: {
    latitude: number
    longitude: number
  }[] = []

  const step = 0.5

  for (
    let latitude = WIND_BOUNDS[1];
    latitude <= WIND_BOUNDS[3];
    latitude += step
  ) {
    for (
      let longitude = WIND_BOUNDS[0];
      longitude <= WIND_BOUNDS[2];
      longitude += step
    ) {
      points.push({
        latitude:
          Number(
            latitude.toFixed(2)
          ),

        longitude:
          Number(
            longitude.toFixed(2)
          ),
      })
    }
  }

  return points
}


/**
 * Find the index of the timestamp closest
 * to a requested Unix timestamp.
 */
function findClosestTimeIndex(
  times: number[],
  targetTimestamp: number
) {
  if (times.length === 0) {
    return -1
  }

  let closestIndex = 0

  let smallestDifference =
    Math.abs(
      times[0] -
      targetTimestamp
    )

  for (
    let index = 1;
    index < times.length;
    index += 1
  ) {
    const difference =
      Math.abs(
        times[index] -
        targetTimestamp
      )

    if (
      difference <
      smallestDifference
    ) {
      smallestDifference =
        difference

      closestIndex =
        index
    }
  }

  return closestIndex
}


/**
 * Build a Deck.gl wind particle layer
 * from one selected point in time.
 */
function createParticleLayer(
  responses:
    OpenMeteoWindResponse[],

  selectedTimestamp:
    number
) {
  const windData: WindDataPoint[] =
    responses
      .map((item) => {
        const times =
          item.hourly?.time ??
          []

        const index =
          findClosestTimeIndex(
            times,
            selectedTimestamp
          )

        if (index < 0) {
          return null
        }

        return {
          lat:
            item.latitude,

          lon:
            item.longitude,

          speed:
            item.hourly
              ?.wind_speed_10m
              ?.[index] ?? 0,

          direction:
            item.hourly
              ?.wind_direction_10m
              ?.[index] ?? 0,
        }
      })
      .filter(
        (
          item
        ): item is WindDataPoint =>
          item !== null &&
          Number.isFinite(
            item.lat
          ) &&
          Number.isFinite(
            item.lon
          ) &&
          Number.isFinite(
            item.speed
          ) &&
          Number.isFinite(
            item.direction
          )
      )

  if (
    windData.length === 0
  ) {
    return null
  }

  const {
    canvas,
    uMin,
    uMax,
    vMin,
    vMax,
  } = generateWindTexture(
    windData,
    {
      width: 300,
      height: 460,
      bounds:
        WIND_BOUNDS,
      power: 2,
    }
  )

  const minVelocity =
    Math.min(
      uMin,
      vMin
    )

  const maxVelocity =
    Math.max(
      uMax,
      vMax
    )

  return new DeckWindParticleLayer({
    id:
      `ecoguard-wind-particles-${selectedTimestamp}`,

    image:
      canvas.toDataURL(),

    bounds:
      WIND_BOUNDS,

    imageUnscale: [
      minVelocity,
      maxVelocity,
    ],

    numParticles:
      3500,

    maxAge:
      110,

    speedFactor:
      55,

    width:
      2.2,

    animate:
      true,

    speedRange: [
      0,
      20,
    ],

    // Neutral greys so wind is visually
    // distinct from rain radar.
    colorRamp: [
      [
        0.0,
        [
          190,
          190,
          190,
          150,
        ],
      ],

      [
        0.35,
        [
          170,
          170,
          170,
          180,
        ],
      ],

      [
        0.65,
        [
          145,
          145,
          145,
          205,
        ],
      ],

      [
        0.85,
        [
          115,
          115,
          115,
          225,
        ],
      ],

      [
        1.0,
        [
          85,
          85,
          85,
          240,
        ],
      ],
    ],
  })
}


function WindParticleLayer({
  timeOffsetHours = 0,
  onTimeChange,
}: WindParticleLayerProps) {

  /**
   * Entire dataset is downloaded once.
   */
  const [
    windResponses,
    setWindResponses,
  ] =
    useState<
      OpenMeteoWindResponse[]
    >([])


  /**
   * Current observation time
   * returned by Open-Meteo.
   */
  const [
    currentTimestamp,
    setCurrentTimestamp,
  ] =
    useState<
      number | null
    >(null)


  /**
   * Loading/error state.
   *
   * We currently surface errors only
   * through the console so the rest of
   * the map remains usable.
   */
  const [
    loading,
    setLoading,
  ] =
    useState(true)


  /**
   * STEP 1
   *
   * Download wind history + forecast
   * exactly once when the layer mounts.
   */
  useEffect(() => {
    let cancelled = false

    const loadWindDataset =
      async () => {

        try {
          setLoading(true)

          const grid =
            buildIsraelWindGrid()

          const latitudes =
            grid
              .map(
                (point) =>
                  point.latitude
              )
              .join(',')

          const longitudes =
            grid
              .map(
                (point) =>
                  point.longitude
              )
              .join(',')

          const params =
            new URLSearchParams({
              latitude:
                latitudes,

              longitude:
                longitudes,

              current:
                'wind_speed_10m,wind_direction_10m',

              hourly:
                'wind_speed_10m,wind_direction_10m',

              wind_speed_unit:
                'ms',

              timezone:
                'Asia/Jerusalem',

              timeformat:
                'unixtime',

              // Supports our -6h timeline.
              past_days:
                '1',

              // Supports our +12h forecast.
              forecast_days:
                '2',
            })

          const response =
            await fetch(
              `https://api.open-meteo.com/v1/forecast?${params.toString()}`
            )

          if (
            !response.ok
          ) {
            throw new Error(
              `Open-Meteo wind request failed with status ${response.status}`
            )
          }

          const data =
            await response.json()

          const responses:
            OpenMeteoWindResponse[] =
            Array.isArray(data)
              ? data
              : [data]

          const firstResponse =
            responses[0]

          const now =
            firstResponse
              ?.current
              ?.time

          if (
            !Number.isFinite(
              now
            )
          ) {
            throw new Error(
              'Open-Meteo did not return a valid current wind timestamp.'
            )
          }

          if (
            cancelled
          ) {
            return
          }

          setWindResponses(
            responses
          )

          setCurrentTimestamp(
            now as number
          )
        } catch (
          error
        ) {
          console.error(
            'Failed to load animated wind dataset:',
            error
          )

          if (
            !cancelled
          ) {
            setWindResponses(
              []
            )

            setCurrentTimestamp(
              null
            )

            onTimeChange?.(
              null
            )
          }
        } finally {
          if (
            !cancelled
          ) {
            setLoading(false)
          }
        }
      }

    loadWindDataset()

    return () => {
      cancelled = true
    }

    /**
     * Intentionally runs once.
     *
     * Moving the timeline must not
     * trigger another API request.
     */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])


  /**
   * STEP 2
   *
   * Calculate which timestamp should
   * be displayed from the cached data.
   */
  const selectedTimestamp =
    useMemo(() => {

      if (
        currentTimestamp ===
          null ||
        windResponses.length ===
          0
      ) {
        return null
      }

      const targetTimestamp =
        currentTimestamp +
        timeOffsetHours *
          60 *
          60

      const referenceTimes =
        windResponses[0]
          ?.hourly
          ?.time ??
        []

      const index =
        findClosestTimeIndex(
          referenceTimes,
          targetTimestamp
        )

      if (
        index < 0
      ) {
        return null
      }

      return (
        referenceTimes[index]
      )
    }, [
      currentTimestamp,
      timeOffsetHours,
      windResponses,
    ])


  /**
   * Notify Dashboard when the selected
   * timeline timestamp changes.
   */
  useEffect(() => {
    onTimeChange?.(
      selectedTimestamp
    )
  }, [
    selectedTimestamp,
    onTimeChange,
  ])


  /**
   * STEP 3
   *
   * Build a new local particle texture
   * whenever the slider changes.
   *
   * No network request occurs here.
   */
  const windLayer =
    useMemo(() => {

      if (
        selectedTimestamp ===
          null ||
        windResponses.length ===
          0
      ) {
        return null
      }

      return (
        createParticleLayer(
          windResponses,
          selectedTimestamp
        )
      )
    }, [
      selectedTimestamp,
      windResponses,
    ])


  if (
    loading ||
    !windLayer
  ) {
    return null
  }


  return (
    <DeckOverlay
      layers={[
        windLayer,
      ]}
    />
  )
}


export default WindParticleLayer