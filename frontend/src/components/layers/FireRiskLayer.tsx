import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Layer, Popup, Source, useMap } from 'react-map-gl/maplibre'
import type { MapLayerMouseEvent } from 'maplibre-gl'
import type { FireRiskCluster } from '../fireRiskClusters'
import type { NationalRiskCell, NationalRiskScan, RiskLevel } from '../fireRiskScan'
import {
  clippedFireRiskFeatureCollection,
  featureCollectionBounds,
} from './fireRiskClipping'

type FireRiskLayerProps = {
  scan: NationalRiskScan | null
  error: string | null
  visible: boolean
  focusedCluster: FireRiskCluster | null
  onClearFocusedCluster: () => void
}

const SOURCE_ID = 'national-fire-risk-source'
const FILL_LAYER_ID = 'national-fire-risk-fill'
const OUTLINE_LAYER_ID = 'national-fire-risk-outline'
const FOCUS_LAYER_ID = 'national-fire-risk-focus'
const FOCUS_SOURCE_ID = 'high-fire-risk-focus-source'
export function fireRiskFeatureCollection(cells: NationalRiskCell[]) {
  return clippedFireRiskFeatureCollection(cells)
}

function FireRiskLayer({ scan, error, visible, focusedCluster, onClearFocusedCluster }: FireRiskLayerProps) {
  const { current: map } = useMap()
  const [selected, setSelected] = useState<NationalRiskCell | null>(null)

  const geojson = useMemo(
    () => fireRiskFeatureCollection(visible ? scan?.cells ?? [] : []),
    [scan, visible],
  )
  const focusGeojson = useMemo(
    () => fireRiskFeatureCollection(focusedCluster?.cells ?? []),
    [focusedCluster],
  )

  useEffect(() => {
    if (!map || !visible) return
    const handleClick = (event: MapLayerMouseEvent) => {
      if (!map.getLayer(FILL_LAYER_ID)) return
      const feature = map.queryRenderedFeatures(event.point, { layers: [FILL_LAYER_ID] })[0]
      if (!feature?.properties) return
      setSelected({
        cell_id: String(feature.properties.cell_id),
        latitude: Number(feature.properties.latitude),
        longitude: Number(feature.properties.longitude),
        risk_score: Number(feature.properties.risk_score),
        risk_level: feature.properties.risk_level as RiskLevel,
        evaluation_time: String(feature.properties.evaluation_time),
      })
    }
    const showPointer = () => { map.getCanvas().style.cursor = 'pointer' }
    const clearPointer = () => { map.getCanvas().style.cursor = '' }
    map.on('click', handleClick)
    map.on('mouseenter', FILL_LAYER_ID, showPointer)
    map.on('mouseleave', FILL_LAYER_ID, clearPointer)
    return () => {
      map.off('click', handleClick)
      map.off('mouseenter', FILL_LAYER_ID, showPointer)
      map.off('mouseleave', FILL_LAYER_ID, clearPointer)
      clearPointer()
    }
  }, [map, visible])

  useEffect(() => {
    if (!map || !focusedCluster) return
    setSelected(focusedCluster.representative_cell)
    const clippedBounds = featureCollectionBounds(focusGeojson)
    if (clippedBounds) map.fitBounds(clippedBounds, { padding: 90, maxZoom: 10, duration: 1200 })
  }, [focusGeojson, focusedCluster, map])

  return (
    <>
      <Source id={SOURCE_ID} type="geojson" data={geojson}>
        <Layer
          id={FILL_LAYER_ID}
          type="fill"
          paint={{
            'fill-color': ['match', ['get', 'risk_level'],
              'high', '#dc2626', 'medium', '#f59e0b', 'low', '#22c55e', '#64748b'],
            'fill-opacity': ['match', ['get', 'risk_level'],
              'high', 0.72, 'medium', 0.42, 'low', 0.16, 0],
          }}
        />
        <Layer
          id={OUTLINE_LAYER_ID}
          type="line"
          paint={{
            'line-color': ['match', ['get', 'risk_level'],
              'high', '#991b1b', 'medium', '#b45309', 'low', '#15803d', '#64748b'],
            'line-opacity': ['match', ['get', 'risk_level'], 'high', 0.95, 'medium', 0.65, 'low', 0.22, 0],
            'line-width': ['match', ['get', 'risk_level'], 'high', 1.8, 'medium', 1, 0.4],
          }}
        />
      </Source>

      <Source id={FOCUS_SOURCE_ID} type="geojson" data={focusGeojson}>
        <Layer id={`${FOCUS_LAYER_ID}-fill`} type="fill"
          paint={{ 'fill-color': '#dc2626', 'fill-opacity': 0.78 }} />
        <Layer id={FOCUS_LAYER_ID} type="line"
          paint={{ 'line-color': '#ffffff', 'line-width': 4, 'line-opacity': 1 }} />
      </Source>

      {visible && <div style={legendStyle}>
        <strong>Current Fire Risk</strong>
        {(['low', 'medium', 'high'] as const).map((level) => (
          <div key={level} style={legendRowStyle}>
            <span style={{ ...swatchStyle, background: level === 'low' ? '#22c55e' : level === 'medium' ? '#f59e0b' : '#dc2626' }} />
            {level.toUpperCase()}
          </div>
        ))}
        {!scan && !error && <div style={statusStyle}>Loading…</div>}
        {error && <div style={errorStyle}>{error}</div>}
      </div>}

      {selected && (
        <Popup
          longitude={selected.longitude}
          latitude={selected.latitude}
          anchor="bottom"
          closeOnClick={false}
          onClose={() => {
            setSelected(null)
            onClearFocusedCluster()
          }}
        >
          <div style={popupStyle}>
            <strong>{selected.risk_level.toUpperCase()} Current Risk</strong>
            <div>Risk score: {(selected.risk_score * 100).toFixed(1)}%</div>
            <div>Evaluated: {new Date(selected.evaluation_time).toLocaleString()}</div>
            {focusedCluster && <div>Selected HIGH area: {focusedCluster.cell_count} {focusedCluster.cell_count === 1 ? 'cell' : 'cells'}</div>}
          </div>
        </Popup>
      )}
    </>
  )
}

const legendStyle: CSSProperties = { position: 'absolute', right: 12, bottom: 36, zIndex: 5,
  background: 'rgba(255,255,255,0.94)', color: '#111827', padding: '10px 12px', borderRadius: 8,
  boxShadow: '0 2px 8px rgba(0,0,0,0.2)', fontSize: '0.8rem', minWidth: 145 }
const legendRowStyle: CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }
const swatchStyle: CSSProperties = { width: 18, height: 12, borderRadius: 2, border: '1px solid rgba(0,0,0,.15)' }
const statusStyle: CSSProperties = { marginTop: 7, color: '#475569' }
const errorStyle: CSSProperties = { marginTop: 7, color: '#b91c1c', maxWidth: 200 }
const popupStyle: CSSProperties = { color: '#111827', display: 'grid', gap: 4, minWidth: 190 }

export default FireRiskLayer
