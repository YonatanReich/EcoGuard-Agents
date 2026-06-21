import requests
import logging
import json
from datetime import datetime, timezone

# Configure logging to easily track the agent's operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class WeatherDataAgent:
    def __init__(self):
        # Base URL for the Open-Meteo API
        self.source_name = "open-meteo"
        self.base_url = "https://api.open-meteo.com/v1/forecast"

    def fetch_weather_data(self, latitude: float, longitude: float) -> dict:
        """
        Fetches weather data from the API for given latitude and longitude 
        and returns a structured dictionary according to the Unified API Contract.
        """
        # Define query parameters: current data and daily forecast (including max wind speed)
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,wind_speed_10m_max,precipitation_sum",
            "timezone": "auto"
        }

        # Generate current timestamp in ISO 8601 format (UTC)
        current_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            # Send request to the API
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            
            data = response.json()
            current_data = data.get("current", {})
            forecast_data = data.get("daily", {})

            # Build the response according to the Unified Environmental Data Format
            unified_data = {
                "metadata": {
                    "timestamp": current_timestamp,
                    "data_source": self.source_name,
                    "collection_status": "success"
                },
                "location": {
                    "latitude": latitude,
                    "longitude": longitude
                },
                "geospatial_context": {
                    "terrain_type": None,
                    "vegetation_density": None,
                    "distance_to_water_m": None
                },
                "weather": {
                    "current": {
                        "temperature_c": current_data.get("temperature_2m"),
                        "humidity_percent": current_data.get("relative_humidity_2m"),  
                        "wind_speed_kmh": current_data.get("wind_speed_10m"),        
                        "precipitation_mm": current_data.get("precipitation"),     
                        "weather_code": current_data.get("weather_code")        
                    },
                    "forecast": {
                        "daily": {
                            "max_temp_c": forecast_data.get("temperature_2m_max", []),
                            "min_temp_c": forecast_data.get("temperature_2m_min", []),
                            "max_wind_speed_kmh": forecast_data.get("wind_speed_10m_max", []),
                            "precipitation_sum_mm": forecast_data.get("precipitation_sum", [])
                        }
                    }
                }
            }

            logging.info(f"Successfully fetched unified weather data for coordinates ({latitude}, {longitude})")
            return unified_data

        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch weather data from API: {e}")
            
            # Return a valid unified format with a 'failed' status
            return {
                "metadata": {
                    "timestamp": current_timestamp,
                    "data_source": self.source_name,
                    "collection_status": "failed"
                },
                "location": {
                    "latitude": latitude,
                    "longitude": longitude
                },
                "geospatial_context": {"terrain_type": None, "vegetation_density": None, "distance_to_water_m": None},
                "weather": {"current": {}, "forecast": {"daily": {}}}
            }
