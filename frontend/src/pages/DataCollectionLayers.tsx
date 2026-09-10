import { useMemo, useRef, useState } from 'react'

import { fetchEnvironmentalData } from '../api/environmentalData'
import EnvironmentalDataModal from '../components/EnvironmentalDataModal'
import FireDangerLegend from '../components/FireDangerLegend'
import InfrastructureLayer from '../components/InfrastructureLayer'
import LayersControl from '../components/LayersControl'
import MapView, { type MapCoordinateClickEvent } from '../components/MapView'
import FireDangerLayer from '../components/layers/FireDangerLayer'
import FireRiskLayer from '../components/layers/FireRiskLayer'
import RainRadarLayer, { type RainViewerFrame } from '../components/layers/RainRadarLayer'
import WindParticleLayer from '../components/layers/WindParticleLayer'
import { useNationalRiskScan } from '../hooks/useNationalRiskScan'
import type { EnvironmentalData } from '../types/environmentalData'

import './visuals/data-collection-layers.css'

type SourceState = 'available' | 'partial' | 'unavailable' | 'idle'

type SourceItem = {
  name: string
  category: string
  description: string
  state: SourceState
  status: string
  updatedAt?: string | number | null
}

function formatTimestamp(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return 'Not available'
  const date = new Date(typeof value === 'number' ? value * 1000 : value)
  return Number.isNaN(date.getTime()) ? 'Not available' : date.toLocaleString()
}

function serviceState(status?: string): SourceState {
  if (!status) return 'idle'
  if (status === 'success') return 'available'
  if (status === 'partial' || status === 'partial_service_failure') return 'partial'
  return 'unavailable'
}

function DataCollectionLayers() {
  const [showRainRadar, setShowRainRadar] = useState(true)
  const [showFireDanger, setShowFireDanger] = useState(false)
  const [showFireRisk, setShowFireRisk] = useState(false)
  const [showWind, setShowWind] = useState(false)
  const [showInfrastructure, setShowInfrastructure] = useState(true)
  const [rainFrames, setRainFrames] = useState<RainViewerFrame[]>([])
  const [rainTimestamp, setRainTimestamp] = useState<number | null>(null)
  const [windTimestamp, setWindTimestamp] = useState<number | null>(null)
  const [selectedLocation, setSelectedLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [environmentalData, setEnvironmentalData] = useState<EnvironmentalData | null>(null)
  const [environmentalError, setEnvironmentalError] = useState<string | null>(null)
  const [isLoadingEnvironmentalData, setIsLoadingEnvironmentalData] = useState(false)
  const [isPopupOpen, setIsPopupOpen] = useState(false)
  const contextRequestIdRef = useRef(0)
  const { scan: nationalRiskScan, error: nationalRiskError } = useNationalRiskScan()

  const handleMapClick = (event: MapCoordinateClickEvent) => {
    const { lat, lng } = event.lngLat

    if (lat < 29.45 || lat > 33.35 || lng < 34.26 || lng > 35.90) return
    const requestId = ++contextRequestIdRef.current

    setSelectedLocation({ lat, lng })
    setIsPopupOpen(true)
    setIsLoadingEnvironmentalData(true)
    setEnvironmentalError(null)
    setEnvironmentalData(null)

    void fetchEnvironmentalData(lat, lng)
      .then((data) => {
        if (contextRequestIdRef.current === requestId) setEnvironmentalData(data)
      })
      .catch((reason: unknown) => {
        if (contextRequestIdRef.current !== requestId) return
        setEnvironmentalError(
          reason instanceof Error ? reason.message : 'Environmental data is unavailable',
        )
      })
      .finally(() => {
        if (contextRequestIdRef.current === requestId) setIsLoadingEnvironmentalData(false)
      })
  }

  const sourceItems = useMemo<SourceItem[]>(() => {
    const weatherStatus = environmentalData?.metadata.services.weather.status
    const geographicStatus = environmentalData?.metadata.services.geospatial.status
    const infrastructureCount = environmentalData
      ? (environmentalData.geospatial_context.nearby_hospitals?.length ?? 0)
        + (environmentalData.geospatial_context.nearby_police_stations?.length ?? 0)
        + (environmentalData.geospatial_context.nearby_fire_stations?.length ?? 0)
      : 0

    return [
      {
        name: environmentalData?.metadata.services.weather.source || 'Open-Meteo weather',
        category: 'Weather',
        description: 'Current conditions and forecast data for a selected map location.',
        state: environmentalError ? 'unavailable' : serviceState(weatherStatus),
        status: environmentalError
          ? 'Request unavailable'
          : isLoadingEnvironmentalData
            ? 'Loading selected location'
            : weatherStatus || 'Select a map location to inspect',
        updatedAt: environmentalData?.metadata.timestamp,
      },
      {
        name: 'RainViewer radar',
        category: 'Weather',
        description: 'Recent precipitation radar frames rendered directly on the map.',
        state: !showRainRadar ? 'idle' : rainFrames.length > 0 ? 'available' : 'idle',
        status: !showRainRadar
          ? 'Layer inactive'
          : rainFrames.length > 0 ? `${rainFrames.length} frames available` : 'Connecting to provider',
        updatedAt: rainTimestamp,
      },
      {
        name: 'Open-Meteo wind',
        category: 'Weather',
        description: 'Animated near-surface wind observations and forecast.',
        state: !showWind ? 'idle' : windTimestamp ? 'available' : 'idle',
        status: !showWind ? 'Layer inactive' : windTimestamp ? 'Available' : 'Connecting to provider',
        updatedAt: windTimestamp,
      },
      {
        name: 'GWIS / EFFIS fire danger',
        category: 'Fire / Satellite',
        description: 'Fire Weather Index overlay; this is environmental danger, not incident detection.',
        state: 'idle',
        status: showFireDanger
          ? 'Layer enabled; provider health is not reported'
          : 'Layer inactive',
      },
      {
        name: 'EcoGuard national current risk',
        category: 'Fire / Satellite',
        description: 'Conditions-based fire-risk estimate; it does not assert that a fire was detected.',
        state: nationalRiskError || nationalRiskScan?.status === 'unavailable'
          ? 'unavailable'
          : nationalRiskScan?.status === 'partial' ? 'partial'
            : nationalRiskScan ? 'available' : 'idle',
        status: nationalRiskError || nationalRiskScan?.status || 'Loading latest scan',
        updatedAt: nationalRiskScan?.evaluation_time,
      },
      {
        name: 'NASA FIRMS detection evidence',
        category: 'Fire / Satellite',
        description: 'FIRMS-derived event detection and service status are exposed through the EcoGuard detected-events pipeline. Raw hotspot records are not exposed as a standalone frontend dataset.',
        state: 'partial',
        status: 'Available through detected-events pipeline',
      },
      {
        name: 'Telegram emergency intelligence',
        category: 'Social / Open Intelligence',
        description: 'Configured Telegram channels can provide environmental or emergency reports to the agent pipeline. Agent-side capability exists, but no frontend-facing status or event endpoint is currently available.',
        state: 'unavailable',
        status: 'Not connected to frontend',
      },
      {
        name: environmentalData?.metadata.services.geospatial.source || 'OpenStreetMap geographic context',
        category: 'Geographic',
        description: 'Land-use context and nearby geographic features for a selected location.',
        state: environmentalError ? 'unavailable' : serviceState(geographicStatus),
        status: environmentalError
          ? 'Request unavailable'
          : isLoadingEnvironmentalData
            ? 'Loading selected location'
            : geographicStatus || 'Select a map location to inspect',
        updatedAt: environmentalData?.metadata.timestamp,
      },
      {
        name: 'Nearby infrastructure',
        category: 'Infrastructure',
        description: 'Hospitals, police stations, and fire stations returned with geographic context.',
        state: environmentalError ? 'unavailable' : serviceState(geographicStatus),
        status: geographicStatus
          ? `${infrastructureCount} nearby features returned`
          : 'Select a map location to inspect',
        updatedAt: environmentalData?.metadata.timestamp,
      },
      {
        name: 'Flood, topography & air quality',
        category: 'Integrations under development',
        description: 'Flood, topography and air-quality integrations are planned or under development; frontend availability depends on merged backend/data-source contracts.',
        state: 'unavailable',
        status: 'Not connected to this frontend',
      },
    ]
  }, [
    environmentalData,
    environmentalError,
    isLoadingEnvironmentalData,
    nationalRiskError,
    nationalRiskScan,
    rainFrames.length,
    rainTimestamp,
    showFireDanger,
    showRainRadar,
    showWind,
    windTimestamp,
  ])

  return (
    <main className="data-layers-page">
      <header className="data-layers-page__header">
        <div>
          <p className="data-layers-page__eyebrow">Environmental intelligence</p>
          <h1>Data Collection &amp; Layers</h1>
          <p>
            Inspect source availability and preview the environmental and geographic layers
            that support EcoGuard analysis. Select a point on the map for local source details.
          </p>
        </div>
      </header>

      <section className="data-layers-page__sources" aria-labelledby="source-overview-title">
        <div className="data-layers-page__section-heading">
          <h2 id="source-overview-title">Data source overview</h2>
          <p>Status reflects only information exposed by the current integrations.</p>
        </div>
        <div className="source-grid">
          {sourceItems.map((source) => (
            <article className="source-card" key={source.name}>
              <div className="source-card__heading">
                <span className="source-card__category">{source.category}</span>
                <span className={`source-status source-status--${source.state}`}>
                  {source.status}
                </span>
              </div>
              <h3>{source.name}</h3>
              <p>{source.description}</p>
              <dl>
                <div>
                  <dt>Last update</dt>
                  <dd>{formatTimestamp(source.updatedAt)}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section className="data-layers-page__map-section" aria-labelledby="map-preview-title">
        <div className="data-layers-page__section-heading">
          <h2 id="map-preview-title">Layer map preview</h2>
          <p>Use the map controls to combine available layers. Click the map to inspect local data.</p>
        </div>
        <div className="data-layers-page__map">
          <MapView
            events={[]}
            onClick={handleMapClick}
            selectedLocation={selectedLocation}
          >
            {showRainRadar && (
              <RainRadarLayer
                onFramesChange={setRainFrames}
                onFrameTimeChange={setRainTimestamp}
              />
            )}
            {showWind && <WindParticleLayer onTimeChange={setWindTimestamp} />}
            {showFireDanger && <FireDangerLayer />}
            {showFireDanger && <FireDangerLegend />}
            {showFireRisk && (
              <FireRiskLayer
                scan={nationalRiskScan}
                error={nationalRiskError}
                visible
                focusedCluster={null}
                onClearFocusedCluster={() => undefined}
              />
            )}
            {showInfrastructure && environmentalData && (
              <InfrastructureLayer
                hospitals={environmentalData.geospatial_context.nearby_hospitals ?? []}
                policeStations={environmentalData.geospatial_context.nearby_police_stations ?? []}
                fireStations={environmentalData.geospatial_context.nearby_fire_stations ?? []}
              />
            )}
            <LayersControl
              showRainRadar={showRainRadar}
              onToggleRainRadar={() => setShowRainRadar((current) => !current)}
              showFireDanger={showFireDanger}
              onToggleFireDanger={() => setShowFireDanger((current) => !current)}
              showFireRisk={showFireRisk}
              onToggleFireRisk={() => setShowFireRisk((current) => !current)}
              showWind={showWind}
              onToggleWind={() => setShowWind((current) => !current)}
              showInfrastructure={showInfrastructure}
              onToggleInfrastructure={() => setShowInfrastructure((current) => !current)}
            />
            <EnvironmentalDataModal
              isOpen={isPopupOpen}
              onClose={() => setIsPopupOpen(false)}
              latitude={selectedLocation?.lat ?? null}
              longitude={selectedLocation?.lng ?? null}
              envData={environmentalData}
              isLoading={isLoadingEnvironmentalData}
              error={environmentalError}
            />
          </MapView>
        </div>
      </section>
    </main>
  )
}

export default DataCollectionLayers
