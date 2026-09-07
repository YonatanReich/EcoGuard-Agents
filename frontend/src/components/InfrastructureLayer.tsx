/**
 * InfrastructureLayer
 *
 * Displays nearby emergency infrastructure returned by the backend for the
 * currently selected location.
 *
 * Supported infrastructure:
 *   - Hospitals
 *   - Police stations
 *   - Fire stations
 *
 * Markers are rendered only from the geospatial_context returned for the
 * selected point. Clicking a marker opens a popup containing its name and
 * category.
 */

import { useState } from 'react'
import { Marker, Popup } from 'react-map-gl/mapbox'
import type { CSSProperties } from 'react'


export type InfrastructureItem = {
  name: string
  type: string
  latitude: number
  longitude: number
  osm_type?: string
  osm_id?: number
}

type InfrastructureLayerProps = {
  hospitals?: InfrastructureItem[]
  policeStations?: InfrastructureItem[]
  fireStations?: InfrastructureItem[]
}

type SelectedItem = InfrastructureItem & {
  icon: string
  category: string
}


function InfrastructureLayer({
  hospitals = [],
  policeStations = [],
  fireStations = [],
}: InfrastructureLayerProps) {
  const [selectedItem, setSelectedItem] =
    useState<SelectedItem | null>(null)

  const items: SelectedItem[] = [
    ...hospitals.map((item) => ({
      ...item,
      icon: '🏥',
      category: 'Hospital',
    })),

    ...policeStations.map((item) => ({
      ...item,
      icon: '🚓',
      category: 'Police Station',
    })),

    ...fireStations.map((item) => ({
      ...item,
      icon: '🚒',
      category: 'Fire Station',
    })),
  ]

  return (
    <>
      {items.map((item) => (
        <Marker
          key={`${item.type}-${item.osm_id ?? item.name}`}
          longitude={item.longitude}
          latitude={item.latitude}
          anchor="center"
        >
          <button
            type="button"
            title={item.name}
            style={markerButtonStyle}
            onClick={(event) => {
              // Prevent the click from reaching the underlying map.
              event.stopPropagation()

              setSelectedItem(item)
            }}
          >
            {item.icon}
          </button>
        </Marker>
      ))}

      {selectedItem && (
        <Popup
          longitude={selectedItem.longitude}
          latitude={selectedItem.latitude}
          anchor="bottom"
          closeOnClick={false}
          closeButton={true}
          offset={24}
          onClose={() => setSelectedItem(null)}
        >
          <div style={popupStyle}>
            <div style={popupTitleStyle}>
              <span>{selectedItem.icon}</span>
              <span>{selectedItem.name}</span>
            </div>

            <div style={popupCategoryStyle}>
              {selectedItem.category}
            </div>
          </div>
        </Popup>
      )}
    </>
  )
}


const markerButtonStyle: CSSProperties = {
  border: 'none',
  background: '#ffffff',
  borderRadius: '50%',
  width: 34,
  height: 34,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: 20,
  cursor: 'pointer',
  boxShadow: '0 2px 6px rgba(0, 0, 0, 0.35)',
  padding: 0,
}


const popupStyle: CSSProperties = {
  minWidth: 170,
  maxWidth: 260,

  // Explicit colours prevent dashboard/global CSS from making
  // Mapbox popup text invisible.
  color: '#111827',
  background: '#ffffff',

  fontFamily: 'Arial, sans-serif',
  padding: '4px 6px',
}


const popupTitleStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  color: '#111827',
  fontSize: '0.9rem',
  fontWeight: 700,
  lineHeight: 1.3,
}


const popupCategoryStyle: CSSProperties = {
  marginTop: 5,
  color: '#6b7280',
  fontSize: '0.78rem',
}


export default InfrastructureLayer