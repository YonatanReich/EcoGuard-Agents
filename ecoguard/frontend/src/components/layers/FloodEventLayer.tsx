import { useMemo, useState, type CSSProperties } from 'react'
import { Layer, Marker, Popup, Source } from 'react-map-gl/mapbox'

import type { FloodEvent, FloodResponseSite, GeographicPoint } from '../../types/events'

const SEVERITY_COLORS: Record<3 | 4 | 5 | 6, string> = {
  3: '#facc15',
  4: '#f97316',
  5: '#ef4444',
  6: '#7f1d1d',
}

function precisionCircle(center: GeographicPoint, radiusM: number) {
  const earthRadiusM = 6_371_000
  const latitude = center.latitude * Math.PI / 180
  const longitude = center.longitude * Math.PI / 180
  const angularDistance = radiusM / earthRadiusM
  const coordinates = Array.from({ length: 65 }, (_, index) => {
    const bearing = index / 64 * Math.PI * 2
    const pointLatitude = Math.asin(
      Math.sin(latitude) * Math.cos(angularDistance)
      + Math.cos(latitude) * Math.sin(angularDistance) * Math.cos(bearing),
    )
    const pointLongitude = longitude + Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latitude),
      Math.cos(angularDistance) - Math.sin(latitude) * Math.sin(pointLatitude),
    )
    return [pointLongitude * 180 / Math.PI, pointLatitude * 180 / Math.PI]
  })
  return coordinates
}

function roadLabel(site: FloodResponseSite) {
  return site.road.ref ?? site.road.name ?? site.road.base_class ?? 'road'
}

function FloodEventLayer({ event, onEventClick }: {
  event: FloodEvent
  onEventClick?: (event: FloodEvent) => void
}) {
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null)
  const color = SEVERITY_COLORS[event.details.severity_level]
  const selectedTarget = event.details.response_sites.find(
    (site) => site.target_id === selectedTargetId,
  ) ?? null

  const streamData = useMemo(() => ({
    type: 'FeatureCollection' as const,
    features: event.details.sources.flatMap((source) => source.stream ? [{
      type: 'Feature' as const,
      properties: {
        stationId: source.station.id,
        streamName: source.stream.name,
      },
      geometry: source.stream.geometry,
    }] : []),
  }), [event.details.sources])

  const uncertaintyData = useMemo(() => ({
    type: 'FeatureCollection' as const,
    features: event.details.sources.flatMap((source) => (
      source.stream === null && source.station.precision_m > 0
        ? [{
            type: 'Feature' as const,
            properties: { stationId: source.station.id },
            geometry: {
              type: 'Polygon' as const,
              coordinates: [precisionCircle(source.station, source.station.precision_m)],
            },
          }]
        : []
    )),
  }), [event.details.sources])

  const connectorData = selectedTarget?.allocation_location ? {
    type: 'Feature' as const,
    properties: {},
    geometry: {
      type: 'LineString' as const,
      coordinates: [
        [selectedTarget.crossing_location.longitude, selectedTarget.crossing_location.latitude],
        [selectedTarget.allocation_location.longitude, selectedTarget.allocation_location.latitude],
      ],
    },
  } : null

  return (
    <>
      {streamData.features.length > 0 && (
        <Source id={`flood-stream-${event.id}`} type="geojson" data={streamData}>
          <Layer
            id={`flood-stream-halo-${event.id}`}
            type="line"
            slot="top"
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            paint={{
              'line-color': color,
              'line-width': 14,
              'line-opacity': 0.2,
              'line-blur': 3,
            }}
          />
          <Layer
            id={`flood-stream-core-${event.id}`}
            type="line"
            slot="top"
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            paint={{ 'line-color': color, 'line-width': 4, 'line-opacity': 0.95 }}
          />
        </Source>
      )}

      {uncertaintyData.features.length > 0 && (
        <Source id={`flood-station-precision-${event.id}`} type="geojson" data={uncertaintyData}>
          <Layer
            id={`flood-station-precision-fill-${event.id}`}
            type="fill"
            slot="top"
            paint={{ 'fill-color': color, 'fill-opacity': 0.08 }}
          />
          <Layer
            id={`flood-station-precision-line-${event.id}`}
            type="line"
            slot="top"
            paint={{
              'line-color': color,
              'line-width': 2,
              'line-opacity': 0.8,
              'line-dasharray': [2, 2],
            }}
          />
        </Source>
      )}

      {event.details.sources.map((source) => (
        <Marker
          key={`flood-station-${event.id}-${source.station.id}`}
          longitude={source.station.longitude}
          latitude={source.station.latitude}
          anchor="center"
        >
          <button
            type="button"
            className="flood-station-marker"
            style={{ '--flood-color': color } as CSSProperties}
            title={`Hydrometric station ${source.station.id}`}
            aria-label={`Hydrometric station ${source.station.id}`}
            onClick={(clickEvent) => {
              clickEvent.stopPropagation()
              onEventClick?.(event)
            }}
          >
            ≋
          </button>
        </Marker>
      ))}

      {event.details.response_sites.map((site) => (
        <Marker
          key={site.target_id}
          longitude={site.crossing_location.longitude}
          latitude={site.crossing_location.latitude}
          anchor="center"
        >
          <button
            type="button"
            className={`flood-crossing-marker${site.allocation_eligible ? '' : ' flood-crossing-marker--unverified'}`}
            title={`${roadLabel(site)} · ${site.crossing_type ?? 'crossing'}`}
            aria-label={`Flood road response site at ${roadLabel(site)}`}
            onClick={(clickEvent) => {
              clickEvent.stopPropagation()
              setSelectedTargetId(site.target_id)
              onEventClick?.(event)
            }}
          >
            ×
          </button>
        </Marker>
      ))}

      {connectorData && selectedTarget?.allocation_location && (
        <>
          <Source id={`flood-access-connector-${event.id}`} type="geojson" data={connectorData}>
            <Layer
              id={`flood-access-connector-line-${event.id}`}
              type="line"
              slot="top"
              paint={{
                'line-color': '#38bdf8',
                'line-width': 2,
                'line-dasharray': [2, 2],
              }}
            />
          </Source>
          <Marker
            longitude={selectedTarget.allocation_location.longitude}
            latitude={selectedTarget.allocation_location.latitude}
            anchor="center"
          >
            <span className="flood-access-marker" title="Mapbox-verified vehicle access point" />
          </Marker>
          <Popup
            longitude={selectedTarget.crossing_location.longitude}
            latitude={selectedTarget.crossing_location.latitude}
            anchor="bottom"
            offset={18}
            closeOnClick={false}
            className="flood-target-popup"
            onClose={() => setSelectedTargetId(null)}
          >
            <div className="flood-target-popup__content">
              <strong>{roadLabel(selectedTarget)}</strong>
              <span>Crossing: {selectedTarget.crossing_type ?? 'unknown'}</span>
              <span>Blue point: verified vehicle access</span>
            </div>
          </Popup>
        </>
      )}
    </>
  )
}

export default FloodEventLayer
