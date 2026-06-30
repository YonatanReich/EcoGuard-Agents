import { type EnvironmentalData } from '../pages/Dashboard'

type ModalProps = {
  isOpen: boolean
  onClose: () => void
  eventTitle?: string
  envData: EnvironmentalData | null
  isLoading: boolean
  error: string | null
}

export default function EnvironmentalDataModal({ 
  isOpen, 
  onClose, 
  eventTitle, 
  envData, 
  isLoading, 
  error 
}: ModalProps) {
  
  if (!isOpen) return null

  return (
    <div className="env-data-modal-overlay">
      <div className="env-data-modal-content">
        
        <div className="env-data-modal-header">
          <h3 className="env-data-modal-title">Environmental Data: {eventTitle}</h3>
          <button 
            className="env-data-modal-close-btn"
            onClick={onClose} 
            aria-label="Close modal"
          >
            ❌
          </button>
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
    </div>
  )
}