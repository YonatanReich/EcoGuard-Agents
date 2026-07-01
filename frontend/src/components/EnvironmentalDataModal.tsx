import { Popup } from 'react-map-gl/maplibre'
import { type EnvironmentalData } from '../pages/Dashboard'
import '../pages/visuals/environmentaldatamodal.css'

type ModalProps = {
  isOpen: boolean
  onClose: () => void
  latitude: number | null
  longitude: number | null
  envData: EnvironmentalData | null
  isLoading: boolean
  error: string | null
}

export default function EnvironmentalDataModal({
  isOpen,
  onClose,
  latitude,
  longitude,
  envData,
  isLoading,
  error
}: ModalProps) {

  if (!isOpen || latitude === null || longitude === null) return null

  const locationTitle = `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`

  return (
    <Popup
      latitude={latitude}
      longitude={longitude}
      closeButton={true}
      closeOnClick={false}
      onClose={onClose}
      anchor="bottom"
      offset={25}
    >
      {/* We removed the .env-data-modal-overlay div entirely! */}
      <div className="env-data-modal-content">

        <div className="env-data-modal-header">
          <h3 className="env-data-modal-title">Data for: {locationTitle}</h3>
        </div>

        {isLoading && (
          <div className="env-data-modal-loading">
            <p>Loading real-time environmental data...</p>
          </div>
        )}

        {error && (
          <div className="env-data-modal-error">
            <p><strong>Error:</strong> {error}</p>
          </div>
        )}

        {envData && !isLoading && (
          <div>
            <div className="env-data-modal-stats">
              <p><strong>Location (Coords):</strong> {envData.location.latitude.toFixed(4)}, {envData.location.longitude.toFixed(4)}</p>
              <p><strong>Temperature:</strong> {envData.weather.current.temperature_c}°C</p>
              <p><strong>Wind Speed:</strong> {envData.weather.current.wind_speed_kmh} km/h</p>
              <p><strong>Humidity:</strong> {envData.weather.current.humidity_percent}%</p>
              <p><strong>Precipitation:</strong> {envData.weather.current.precipitation_mm} mm</p>
            </div>
          </div>
        )}
      </div>
    </Popup>
  )
}