import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from 'react'

import {
  CallbackProperty,
  Cartesian3,
  Color,
  createGooglePhotorealistic3DTileset,
  DistanceDisplayCondition,
  Entity,
  Ion,
  JulianDate,
  Math as CesiumMath,
  NearFarScalar,
  Quaternion,
  SampledPositionProperty,
  TimeInterval,
  TimeIntervalCollection,
  VelocityOrientationProperty,
  VerticalOrigin,
  Viewer,
} from 'cesium'

import { useSearchParams } from 'react-router-dom'

import 'cesium/Build/Cesium/Widgets/widgets.css'


const DEFAULT_FIRE_LONGITUDE = 34.8976
const DEFAULT_FIRE_LATITUDE = 31.9183

const DEFAULT_RISK_SCORE = 82
const RISK_RADIUS_METERS = 850


let googleTilesetPromise:
  | ReturnType<typeof createGooglePhotorealistic3DTileset>
  | null = null


type InfrastructureItem = {
  name: string
  type: string
  latitude: number
  longitude: number
  osm_type?: string
  osm_id?: number
}


type EnvironmentalData = {
  geospatial_context?: {
    nearby_hospitals?: InfrastructureItem[]
    nearby_police_stations?: InfrastructureItem[]
    nearby_fire_stations?: InfrastructureItem[]
    [key: string]: any
  }
}


type OsrmRoute = {
  distance: number
  duration: number
  geometry: {
    type: string
    coordinates: [number, number][]
  }
}


type OsrmResponse = {
  code: string
  routes?: OsrmRoute[]
}


type ResponseUnitConfig = {
  id: string
  label: string
  icon: string
  modelUri: string
  color: Color
  source: InfrastructureItem
  simulationSpeed: number
  minimumPixelSize: number
  viewFrom: Cartesian3
}


function calculateDistanceKm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
) {
  const earthRadiusKm = 6371

  const dLat =
    CesiumMath.toRadians(
      lat2 - lat1,
    )

  const dLon =
    CesiumMath.toRadians(
      lon2 - lon1,
    )

  const a =
    Math.sin(dLat / 2) *
      Math.sin(dLat / 2) +
    Math.cos(
      CesiumMath.toRadians(lat1),
    ) *
      Math.cos(
        CesiumMath.toRadians(lat2),
      ) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2)

  const c =
    2 *
    Math.atan2(
      Math.sqrt(a),
      Math.sqrt(1 - a),
    )

  return earthRadiusKm * c
}


function formatCesiumPlaceName(
  text: string,
) {
  const containsHebrew =
    /[\u0590-\u05FF]/.test(text)

  if (!containsHebrew) {
    return text
  }

  return Array.from(text)
    .reverse()
    .join('')
}


function formatDuration(
  durationSeconds: number,
) {
  const totalMinutes =
    Math.max(
      1,
      Math.round(
        durationSeconds / 60,
      ),
    )

  if (totalMinutes < 60) {
    return `${totalMinutes} min`
  }

  const hours =
    Math.floor(
      totalMinutes / 60,
    )

  const minutes =
    totalMinutes % 60

  return `${hours}h ${minutes}m`
}


async function fetchRoute(
  startLongitude: number,
  startLatitude: number,
  endLongitude: number,
  endLatitude: number,
) {
  const url =
    `https://router.project-osrm.org/route/v1/driving/` +
    `${startLongitude},${startLatitude};` +
    `${endLongitude},${endLatitude}` +
    `?overview=full&geometries=geojson`

  const response =
    await fetch(url)

  if (!response.ok) {
    throw new Error(
      `OSRM returned ${response.status}`,
    )
  }

  const data:
    OsrmResponse =
      await response.json()

  if (
    data.code !== 'Ok' ||
    !data.routes ||
    data.routes.length === 0
  ) {
    throw new Error(
      'No route returned by OSRM',
    )
  }

  return data.routes[0]
}


function getNearestItem(
  items: InfrastructureItem[],
  fireLatitude: number,
  fireLongitude: number,
) {
  if (items.length === 0) {
    return null
  }

  return [...items]
    .sort(
      (a, b) =>
        calculateDistanceKm(
          fireLatitude,
          fireLongitude,
          a.latitude,
          a.longitude,
        )
        -
        calculateDistanceKm(
          fireLatitude,
          fireLongitude,
          b.latitude,
          b.longitude,
        ),
    )[0]
}


export default function Incident3DView() {
  const [searchParams] =
    useSearchParams()

  const parsedLatitude =
    Number(
      searchParams.get('lat')
    )

  const parsedLongitude =
    Number(
      searchParams.get('lng')
    )

  const parsedRiskScore =
    Number(
      searchParams.get(
        'riskScore'
      )
    )

  const fireLatitude =
    Number.isFinite(
      parsedLatitude
    )
      ? parsedLatitude
      : DEFAULT_FIRE_LATITUDE

  const fireLongitude =
    Number.isFinite(
      parsedLongitude
    )
      ? parsedLongitude
      : DEFAULT_FIRE_LONGITUDE

  const riskScore =
    Number.isFinite(
      parsedRiskScore
    )
      ? parsedRiskScore
      : DEFAULT_RISK_SCORE

  const cesiumContainerRef =
    useRef<HTMLDivElement | null>(null)

  const viewerRef =
    useRef<Viewer | null>(null)

  const policeUnitRef =
    useRef<Entity | null>(null)

  const fireUnitRef =
    useRef<Entity | null>(null)

  const ambulanceUnitRef =
    useRef<Entity | null>(null)

  const [
    followedUnit,
    setFollowedUnit,
  ] = useState<
    'police' |
    'fire' |
    'ambulance' |
    null
  >(null)


  // =========================================================
  // Camera controls
  // =========================================================

  const stopFollowing = () => {
    const viewer =
      viewerRef.current

    if (!viewer) {
      return
    }

    viewer.trackedEntity =
      undefined

    setFollowedUnit(
      null,
    )
  }


  const zoomIn = () => {
    const viewer =
      viewerRef.current

    if (!viewer) {
      return
    }

    stopFollowing()

    viewer.camera.zoomIn(
      500,
    )
  }


  const zoomOut = () => {
    const viewer =
      viewerRef.current

    if (!viewer) {
      return
    }

    stopFollowing()

    viewer.camera.zoomOut(
      500,
    )
  }


  const focusFire = () => {
    const viewer =
      viewerRef.current

    if (!viewer) {
      return
    }

    stopFollowing()

    viewer.camera.flyTo({
      destination:
        Cartesian3.fromDegrees(
          fireLongitude,
          fireLatitude,
          4200,
        ),

      orientation: {
        heading:
          0,

        pitch:
          CesiumMath.toRadians(
            -72,
          ),

        roll:
          0,
      },

      duration:
        1.2,
    })
  }


  const topView = () => {
    const viewer =
      viewerRef.current

    if (!viewer) {
      return
    }

    stopFollowing()

    viewer.camera.flyTo({
      destination:
        Cartesian3.fromDegrees(
          fireLongitude,
          fireLatitude,
          5500,
        ),

      orientation: {
        heading:
          0,

        pitch:
          CesiumMath.toRadians(
            -90,
          ),

        roll:
          0,
      },

      duration:
        1.2,
    })
  }


  const threeDView = () => {
    const viewer =
      viewerRef.current

    if (!viewer) {
      return
    }

    stopFollowing()

    viewer.camera.flyTo({
      destination:
        Cartesian3.fromDegrees(
          fireLongitude - 0.018,
          fireLatitude - 0.018,
          2400,
        ),

      orientation: {
        heading:
          CesiumMath.toRadians(
            25,
          ),

        pitch:
          CesiumMath.toRadians(
            -38,
          ),

        roll:
          0,
      },

      duration:
        1.2,
    })
  }


  const resetNorth = () => {
    const viewer =
      viewerRef.current

    if (!viewer) {
      return
    }

    stopFollowing()

    viewer.camera.flyTo({
      destination:
        viewer.camera.position,

      orientation: {
        heading:
          0,

        pitch:
          viewer.camera.pitch,

        roll:
          0,
      },

      duration:
        0.8,
    })
  }


  const followUnit = (
    type:
      'police' |
      'fire' |
      'ambulance',
  ) => {
    const viewer =
      viewerRef.current

    if (!viewer) {
      return
    }

    let entity:
      Entity | null =
        null

    if (
      type ===
      'police'
    ) {
      entity =
        policeUnitRef.current
    }

    if (
      type ===
      'fire'
    ) {
      entity =
        fireUnitRef.current
    }

    if (
      type ===
      'ambulance'
    ) {
      entity =
        ambulanceUnitRef.current
    }

    if (!entity) {
      return
    }

    viewer.trackedEntity =
      entity

    setFollowedUnit(
      type,
    )
  }


  // =========================================================
  // Cesium
  // =========================================================

  useEffect(() => {
    const container =
      cesiumContainerRef.current

    if (!container) {
      return
    }


    Ion.defaultAccessToken =
      import.meta.env
        .VITE_CESIUM_ION_TOKEN


    let cancelled =
      false


    const viewer =
      new Viewer(
        container,
        {
          globe:
            false,

          animation:
            false,

          timeline:
            false,

          geocoder:
            false,

          homeButton:
            false,

          sceneModePicker:
            false,

          navigationHelpButton:
            false,

          fullscreenButton:
            false,

          baseLayerPicker:
            false,

          infoBox:
            false,

          selectionIndicator:
            false,

          shouldAnimate:
            true,
        },
      )


    viewerRef.current =
      viewer


    const initializeScene =
      async () => {

        try {

          // ===================================================
          // Google Photorealistic 3D
          // ===================================================

          if (!googleTilesetPromise) {
            googleTilesetPromise =
              createGooglePhotorealistic3DTileset()
          }


          const tileset =
            await googleTilesetPromise


          if (
            cancelled ||
            viewer.isDestroyed()
          ) {
            return
          }


          viewer.scene.primitives.add(
            tileset,
          )


          // ===================================================
          // Fire
          // ===================================================

          viewer.entities.add({
            name:
              'Wildfire Event',

            position:
              Cartesian3.fromDegrees(
                fireLongitude,
                fireLatitude,
                130,
              ),

            point: {
              pixelSize:
                26,

              color:
                Color.RED,

              outlineColor:
                Color.WHITE,

              outlineWidth:
                4,

              scaleByDistance:
                new NearFarScalar(
                  100,
                  1.4,
                  10000,
                  0.7,
                ),
            },

            label: {
              text:
                `🔥 FIRE EVENT\n` +
                `HIGH RISK — ${riskScore}/100`,

              font:
                'bold 18px sans-serif',

              fillColor:
                Color.WHITE,

              showBackground:
                true,

              backgroundColor:
                Color.BLACK.withAlpha(
                  0.82,
                ),

              pixelOffset:
                new Cartesian3(
                  0,
                  -55,
                  0,
                ),

              verticalOrigin:
                VerticalOrigin.BOTTOM,
            },
          })


          // ===================================================
          // Risk zone
          // ===================================================

          viewer.entities.add({
            name:
              'Wildfire Risk Zone',

            position:
              Cartesian3.fromDegrees(
                fireLongitude,
                fireLatitude,
                70,
              ),

            ellipse: {
              semiMajorAxis:
                RISK_RADIUS_METERS,

              semiMinorAxis:
                RISK_RADIUS_METERS,

              material:
                Color.RED.withAlpha(
                  0.15,
                ),

              outline:
                true,

              outlineColor:
                Color.RED.withAlpha(
                  0.8,
                ),

              height:
                70,
            },
          })


          // ===================================================
          // Backend infrastructure
          // ===================================================

          const response =
            await fetch(
              `/api/environmental-data` +
              `?latitude=${fireLatitude}` +
              `&longitude=${fireLongitude}`,
            )


          if (!response.ok) {
            throw new Error(
              `Environmental API returned ${response.status}`,
            )
          }


          const data:
            EnvironmentalData =
              await response.json()


          if (
            cancelled ||
            viewer.isDestroyed()
          ) {
            return
          }


          const context =
            data.geospatial_context ??
            {}


          const hospitals =
            context
              .nearby_hospitals ??
            []


          const policeStations =
            context
              .nearby_police_stations ??
            []


          const fireStations =
            context
              .nearby_fire_stations ??
            []


          // ===================================================
          // Infrastructure markers
          // ===================================================

          const addInfrastructure =
            (
              item:
                InfrastructureItem,

              icon:
                string,

              category:
                string,

              color:
                Color,
            ) => {

              const distanceKm =
                calculateDistanceKm(
                  fireLatitude,
                  fireLongitude,
                  item.latitude,
                  item.longitude,
                )


              viewer.entities.add({
                name:
                  `${category}: ${item.name}`,

                position:
                  Cartesian3.fromDegrees(
                    item.longitude,
                    item.latitude,
                    120,
                  ),

                point: {
                  pixelSize:
                    18,

                  color,

                  outlineColor:
                    Color.WHITE,

                  outlineWidth:
                    3,
                },

                label: {
                  text:
                    `${icon} ${formatCesiumPlaceName(
                      item.name,
                    )}\n` +
                    `${distanceKm.toFixed(
                      1,
                    )} km`,

                  font:
                    'bold 15px sans-serif',

                  fillColor:
                    Color.WHITE,

                  showBackground:
                    true,

                  backgroundColor:
                    Color.BLACK.withAlpha(
                      0.72,
                    ),

                  distanceDisplayCondition:
                    new DistanceDisplayCondition(
                      0,
                      5000,
                    ),

                  scaleByDistance:
                    new NearFarScalar(
                      500,
                      1,
                      5000,
                      0.75,
                    ),

                  pixelOffset:
                    new Cartesian3(
                      0,
                      -40,
                      0,
                    ),

                  verticalOrigin:
                    VerticalOrigin.BOTTOM,
                },
              })
            }


          hospitals.forEach(
            (hospital) =>
              addInfrastructure(
                hospital,
                '🏥',
                'Hospital',
                Color.DODGERBLUE,
              ),
          )


          policeStations.forEach(
            (station) =>
              addInfrastructure(
                station,
                '🚓',
                'Police Station',
                Color.CYAN,
              ),
          )


          fireStations.forEach(
            (station) =>
              addInfrastructure(
                station,
                '🚒',
                'Fire Station',
                Color.ORANGE,
              ),
          )


          // ===================================================
          // Nearest real infrastructure returned by the backend
          // ===================================================

          const nearestPolice =
            getNearestItem(
              policeStations,
              fireLatitude,
              fireLongitude,
            )


          const nearestFireStation =
            getNearestItem(
              fireStations,
              fireLatitude,
              fireLongitude,
            )


          const nearestHospital =
            getNearestItem(
              hospitals,
              fireLatitude,
              fireLongitude,
            )


          // ===================================================
          // Unit configs
          //
          // One unit of each type for demonstration only.
          // B will determine quantities later.
          // ===================================================

          const units:
            ResponseUnitConfig[] =
              []


          if (nearestPolice) {
            units.push({
              id:
                'police',

              label:
                'Police Unit 1',

              icon:
                '🚓',

              modelUri:
                '/models/police_car.glb',

              color:
                Color.CYAN,

              source:
                nearestPolice,

              simulationSpeed:
                8,

              minimumPixelSize:
                45,

              viewFrom:
                new Cartesian3(
                  -180,
                  -220,
                  140,
                ),
            })
          }


          if (nearestFireStation) {
            units.push({
              id:
                'fire',

              label:
                'Fire Unit 1',

              icon:
                '🚒',

              modelUri:
                '/models/fire_truck.glb',

              color:
                Color.ORANGERED,

              source:
                nearestFireStation,

              simulationSpeed:
                8,

              minimumPixelSize:
                55,

              viewFrom:
                new Cartesian3(
                  -230,
                  -280,
                  180,
                ),
            })
          }


          if (nearestHospital) {
            units.push({
              id:
                'ambulance',

              label:
                'Ambulance 1',

              icon:
                '🚑',

              modelUri:
                '/models/ambulance.glb',

              color:
                Color.LIME,

              source:
                nearestHospital,

              simulationSpeed:
                8,

              minimumPixelSize:
                50,

              viewFrom:
                new Cartesian3(
                  -200,
                  -250,
                  160,
                ),
            })
          }


          // ===================================================
          // Create all routes first
          // ===================================================

          const routeResults =
            await Promise.all(
              units.map(
                async (unit) => {
                  const route =
                    await fetchRoute(
                      unit.source
                        .longitude,

                      unit.source
                        .latitude,

                      fireLongitude,
                      fireLatitude,
                    )

                  return {
                    unit,
                    route,
                  }
                },
              ),
            )


          if (
            cancelled ||
            viewer.isDestroyed()
          ) {
            return
          }


          // ===================================================
          // Shared simulation clock
          // ===================================================

          const startTime =
            JulianDate.now()


          const maxSimulatedDuration =
            Math.max(
              ...routeResults.map(
                ({
                  unit,
                  route,
                }) =>
                  Math.max(
                    20,
                    route.duration /
                      unit.simulationSpeed,
                  ),
              ),
            )


          const stopTime =
            JulianDate.addSeconds(
              startTime,
              maxSimulatedDuration,
              new JulianDate(),
            )


          viewer.clock.startTime =
            startTime.clone()


          viewer.clock.stopTime =
            stopTime.clone()


          viewer.clock.currentTime =
            startTime.clone()


          viewer.clock.shouldAnimate =
            true


          // ===================================================
          // Create response unit
          // ===================================================

          for (
            const {
              unit,
              route,
            }
            of routeResults
          ) {

            const routeCoordinates =
              route.geometry
                .coordinates


            const routePositions =
              routeCoordinates
                .flatMap(
                  (
                    [
                      longitude,
                      latitude,
                    ],
                  ) => [
                    longitude,
                    latitude,
                    112,
                  ],
                )


            // =============================================
            // Route line
            // =============================================

            viewer.entities.add({
              name:
                `${unit.label} Route`,

              polyline: {
                positions:
                  Cartesian3
                    .fromDegreesArrayHeights(
                      routePositions,
                    ),

                width:
                  6,

                material:
                  unit.color.withAlpha(
                    0.88,
                  ),
              },
            })


            const simulatedDuration =
              Math.max(
                20,
                route.duration /
                  unit.simulationSpeed,
              )


            const unitStopTime =
              JulianDate.addSeconds(
                startTime,
                simulatedDuration,
                new JulianDate(),
              )


            const positionProperty =
              new SampledPositionProperty()


            routeCoordinates.forEach(
              (
                [
                  longitude,
                  latitude,
                ],
                index,
              ) => {

                const progress =
                  routeCoordinates.length >
                  1
                    ? index /
                      (
                        routeCoordinates.length -
                        1
                      )
                    : 0


                const time =
                  JulianDate.addSeconds(
                    startTime,

                    simulatedDuration *
                      progress,

                    new JulianDate(),
                  )


                positionProperty
                  .addSample(
                    time,

                    Cartesian3.fromDegrees(
                      longitude,
                      latitude,
                      118,
                    ),
                  )

              },
            )


            const velocityOrientation =
              new VelocityOrientationProperty(
                positionProperty,
              )


            const correctedOrientation =
              unit.id === 'fire'
                ? new CallbackProperty(
                    (time) => {
                      const baseOrientation =
                        velocityOrientation
                          .getValue(
                            time,
                          )

                      if (!baseOrientation) {
                        return undefined
                      }

                      const correction =
                        Quaternion.fromAxisAngle(
                          Cartesian3.UNIT_Z,
                          CesiumMath.toRadians(
                            90,
                          ),
                        )

                      return Quaternion.multiply(
                        baseOrientation,
                        correction,
                        new Quaternion(),
                      )
                    },

                    false,
                  )
                : velocityOrientation


            const entity =
              viewer.entities.add({
                name:
                  unit.label,

                availability:
                  new TimeIntervalCollection([
                    new TimeInterval({
                      start:
                        startTime,

                      stop:
                        unitStopTime,
                    }),
                  ]),

                position:
                  positionProperty,

                orientation:
                  correctedOrientation,

                viewFrom:
                  unit.viewFrom,

                model: {
                  uri:
                    unit.modelUri,

                  minimumPixelSize:
                    unit.minimumPixelSize,

                  maximumScale:
                    140,

                  scale:
                    1,

                  runAnimations:
                    true,
                },

                label: {
                  text:
                    new CallbackProperty(
                      () => {

                        const current =
                          viewer.clock
                            .currentTime


                        const elapsedSeconds =
                          JulianDate
                            .secondsDifference(
                              current,
                              startTime,
                            )


                        const progress =
                          Math.min(
                            1,
                            Math.max(
                              0,

                              elapsedSeconds /
                                simulatedDuration,
                            ),
                          )


                        const remainingSeconds =
                          route.duration *
                          (
                            1 -
                            progress
                          )


                        const remainingKm =
                          (
                            route.distance *
                            (
                              1 -
                              progress
                            )
                          ) /
                          1000


                        if (
                          progress >=
                          0.99
                        ) {
                          return (
                            `${unit.icon} ${unit.label}\n` +
                            `ON SCENE`
                          )
                        }


                        return (
                          `${unit.icon} ${unit.label}\n` +
                          `EN ROUTE\n` +
                          `ETA ${formatDuration(
                            remainingSeconds,
                          )}\n` +
                          `${remainingKm.toFixed(
                            1,
                          )} km remaining`
                        )
                      },

                      false,
                    ),

                  font:
                    'bold 15px sans-serif',

                  fillColor:
                    Color.WHITE,

                  showBackground:
                    true,

                  backgroundColor:
                    Color.BLACK.withAlpha(
                      0.8,
                    ),

                  pixelOffset:
                    new Cartesian3(
                      unit.id === 'police'
                        ? -170
                        : unit.id === 'ambulance'
                          ? 170
                          : 0,
                      -65,
                      0,
                    ),

                  verticalOrigin:
                    VerticalOrigin.BOTTOM,
                },
              })


            if (
              unit.id ===
              'police'
            ) {
              policeUnitRef.current =
                entity
            }


            if (
              unit.id ===
              'fire'
            ) {
              fireUnitRef.current =
                entity
            }


            if (
              unit.id ===
              'ambulance'
            ) {
              ambulanceUnitRef.current =
                entity
            }


            console.log(
              `${unit.label} ready:`,
              {
                from:
                  unit.source.name,

                routeKm:
                  (
                    route.distance /
                    1000
                  ).toFixed(
                    2,
                  ),

                etaMin:
                  (
                    route.duration /
                    60
                  ).toFixed(
                    1,
                  ),
              },
            )
          }


          // ===================================================
          // Command center view
          // ===================================================

          viewer.camera.flyTo({
            destination:
              Cartesian3.fromDegrees(
                fireLongitude,
                fireLatitude,
                7000,
              ),

            orientation: {
              heading:
                0,

              pitch:
                CesiumMath.toRadians(
                  -78,
                ),

              roll:
                0,
            },

            duration:
              2,
          })

        } catch (error) {

          console.error(
            'Failed to initialize 3D incident scene:',
            error,
          )

        }

      }


    initializeScene()


    return () => {

      cancelled =
        true


      policeUnitRef.current =
        null

      fireUnitRef.current =
        null

      ambulanceUnitRef.current =
        null


      viewerRef.current =
        null


      if (
        !viewer.isDestroyed()
      ) {
        viewer.destroy()
      }


      container.innerHTML =
        ''

    }

  }, [
    fireLatitude,
    fireLongitude,
    riskScore,
  ])


  return (
    <div
      style={
        rootStyle
      }
    >

      <div
        ref={
          cesiumContainerRef
        }

        style={
          cesiumStyle
        }
      />


      <div
        style={
          controlsStyle
        }
      >

        <button
          style={
            controlButtonStyle
          }

          onClick={
            zoomIn
          }
        >
          +
        </button>


        <button
          style={
            controlButtonStyle
          }

          onClick={
            zoomOut
          }
        >
          −
        </button>


        <div
          style={
            dividerStyle
          }
        />


        <button
          style={
            controlButtonStyle
          }

          onClick={
            resetNorth
          }
        >
          N
        </button>


        <button
          style={
            wideButtonStyle
          }

          onClick={
            topView
          }
        >
          TOP
        </button>


        <button
          style={
            wideButtonStyle
          }

          onClick={
            threeDView
          }
        >
          ◈ 3D
        </button>


        <button
          style={
            wideButtonStyle
          }

          onClick={
            focusFire
          }
        >
          🔥 FIRE
        </button>


        <div
          style={
            dividerStyle
          }
        />


        <button
          style={{
            ...wideButtonStyle,

            background:
              followedUnit ===
              'police'
                ? '#0e7490'
                : wideButtonStyle
                    .background,
          }}

          onClick={() =>
            followUnit(
              'police',
            )
          }
        >
          🚓 POLICE
        </button>


        <button
          style={{
            ...wideButtonStyle,

            background:
              followedUnit ===
              'fire'
                ? '#b91c1c'
                : wideButtonStyle
                    .background,
          }}

          onClick={() =>
            followUnit(
              'fire',
            )
          }
        >
          🚒 FIRE TRUCK
        </button>


        <button
          style={{
            ...wideButtonStyle,

            background:
              followedUnit ===
              'ambulance'
                ? '#15803d'
                : wideButtonStyle
                    .background,
          }}

          onClick={() =>
            followUnit(
              'ambulance',
            )
          }
        >
          🚑 AMBULANCE
        </button>


        {followedUnit && (
          <button
            style={
              wideButtonStyle
            }

            onClick={
              stopFollowing
            }
          >
            FREE VIEW
          </button>
        )}

      </div>

    </div>
  )
}


// =========================================================
// Styles
// =========================================================

const rootStyle:
  CSSProperties = {
    position:
      'relative',

    width:
      '100%',

    height:
      '100vh',

    overflow:
      'hidden',
  }


const cesiumStyle:
  CSSProperties = {
    width:
      '100%',

    height:
      '100%',
  }


const controlsStyle:
  CSSProperties = {
    position:
      'absolute',

    top:
      18,

    right:
      18,

    zIndex:
      20,

    display:
      'flex',

    flexDirection:
      'column',

    gap:
      6,

    padding:
      8,

    background:
      'rgba(10, 18, 30, 0.82)',

    backdropFilter:
      'blur(10px)',

    border:
      '1px solid rgba(255,255,255,0.18)',

    borderRadius:
      14,

    boxShadow:
      '0 4px 20px rgba(0,0,0,0.35)',
  }


const controlButtonStyle:
  CSSProperties = {
    width:
      46,

    height:
      46,

    border:
      'none',

    borderRadius:
      10,

    background:
      'rgba(16, 24, 39, 0.90)',

    color:
      '#ffffff',

    fontSize:
      22,

    fontWeight:
      700,

    cursor:
      'pointer',
  }


const wideButtonStyle:
  CSSProperties = {
    minWidth:
      110,

    height:
      40,

    border:
      'none',

    borderRadius:
      9,

    padding:
      '0 10px',

    background:
      'rgba(16, 24, 39, 0.90)',

    color:
      '#ffffff',

    fontSize:
      12,

    fontWeight:
      700,

    cursor:
      'pointer',
  }


const dividerStyle:
  CSSProperties = {
    height:
      1,

    background:
      'rgba(255,255,255,0.18)',

    margin:
      '3px 0',
  }
