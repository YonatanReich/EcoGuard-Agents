/**
 * EnvironmentalDataModal — the popup showing readings for a clicked point.
 *
 * Purely presentational: it renders whichever of the three states Dashboard
 * hands it (loading, error, or data) and owns none of them. All fetching
 * lives in Dashboard.
 *
 * Despite the name it is not a modal overlay but a maplibre Popup anchored to
 * the coordinate on the map, which is why it must be rendered inside MapView.
 */

import { Popup } from 'react-map-gl/maplibre'
import type { EnvironmentalData } from '../types/environmentalData'
import '../pages/visuals/environmentaldatamodal.css'

type ModalProps = {
  /** Whether the popup should be shown at all. */
  isOpen: boolean
  /** Called when the user dismisses the popup via its close button. */
  onClose: () => void
  /** Anchor coordinate. Null until the user has clicked somewhere. */
  latitude: number | null
  longitude: number | null
  /** The readings to display, or null while loading or after an error. */
  envData: EnvironmentalData | null
  isLoading: boolean
  /** Display-ready error message, or null if the request succeeded. */
  error: string | null
}

/**
 * Render the environmental data popup.
 *
 * Renders nothing when closed or when there is no coordinate to anchor to.
 * Currently surfaces only the current-weather fields; the forecast and
 * geospatial sections of the response are fetched but not yet displayed.
 */
export default function EnvironmentalDataModal({
  isOpen,
  onClose,
  latitude,
  longitude,
  envData,
  isLoading,
  error
}: ModalProps) {

  // Nothing to anchor to, or nothing to show — render no popup at all.
  if (!isOpen || latitude === null || longitude === null) return null

  // Raw map coordinates carry far more precision than is meaningful here;
  // four decimals is roughly 11 metres and keeps the header readable.
  const locationTitle = `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`

  return (
    <Popup
      latitude={latitude}
      longitude={longitude}
      closeButton={true}
      // Keep the popup open when the user clicks the map, so they can pan and
      // compare without losing the reading; only the close button dismisses it.
      closeOnClick={false}
      onClose={onClose}
      anchor="bottom"
      offset={25}
    >
      {/* No overlay wrapper: the Popup positions itself against the map, and
          a full-screen overlay would block map interaction behind it. */}
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
