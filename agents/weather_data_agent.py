"""
Weather Data Agent

Responsible for collecting real-time weather observations and a short-range
forecast for a single coordinate, using the Open-Meteo public API.

Open-Meteo is free and requires no API key. Typical response time is under
two seconds.

The agent never raises on network failure. Instead it returns the same
unified structure with metadata.collection_status set to "failed", so
callers can merge results from several agents without special-casing errors.

Consumed by: backend.main.get_environmental_data,
             services.multi_location_collection_service
"""

import requests
import logging
import json
from datetime import datetime, timezone

# Configure logging to easily track the agent's operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class WeatherDataAgent:
    """
    Fetches and normalizes weather data for a coordinate.

    Attributes:
        source_name (str): Provider label copied into metadata.data_source
            so consumers can tell which service produced the reading.
        base_url (str): Open-Meteo forecast endpoint.
    """

    def __init__(self):
        # Base URL for the Open-Meteo API
        self.source_name = "open-meteo"
        self.base_url = "https://api.open-meteo.com/v1/forecast"

    def fetch_weather_data(self, latitude: float, longitude: float) -> dict:
        """
        Fetches weather data from the API for given latitude and longitude
        and returns a structured dictionary according to the Unified API Contract.

        Args:
            latitude (float): Location latitude in decimal degrees.
            longitude (float): Location longitude in decimal degrees.

        Returns:
            dict: Unified environmental record containing:
                - metadata: timestamp, data_source, collection_status
                  ("success" or "failed").
                - location: the coordinates that were requested.
                - geospatial_context: always empty here. This agent does not
                  produce geospatial data, but the key is present so the
                  shape matches GeospatialContextAgent's output and the two
                  can be merged without key checks.
                - weather.current: temperature_c, humidity_percent,
                  wind_speed_kmh, precipitation_mm, weather_code.
                - weather.forecast.daily: parallel arrays, one entry per
                  forecast day, for max/min temp, max wind and total
                  precipitation.

            On failure the same shape is returned with collection_status
            "failed" and empty weather sections. No exception propagates.
        """
        # Define query parameters: current data and daily forecast (including max wind speed)
        # timezone=auto makes Open-Meteo align the daily buckets to local
        # midnight at the requested coordinate rather than UTC.
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
                    "region_type": None,
                    "vegetation_density": None,
                    "distance_to_water_m": None,
                    "nearby_roads": [],
                    "nearby_settlements": [],
                    "nearby_hospitals": [],
                    "nearby_police_stations": [],
                    "nearby_fire_stations": [],
                    "nearby_green_areas": [],
                    "nearby_water_sources": []
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

            # Degrade gracefully rather than raising: the caller merges this
            # with the geospatial agent's result and can still serve a partial
            # response if only one of the two providers is down.
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
                "geospatial_context": {
                    "terrain_type": None,
                    "region_type": None,
                    "vegetation_density": None,
                    "distance_to_water_m": None,
                    "nearby_roads": [],
                    "nearby_settlements": [],
                    "nearby_hospitals": [],
                    "nearby_police_stations": [],
                    "nearby_fire_stations": [],
                    "nearby_green_areas": [],
                    "nearby_water_sources": []
                },
                "weather": {"current": {}, "forecast": {"daily": {}}}
            }