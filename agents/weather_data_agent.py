import requests
import logging

# Configure logging to easily track the agent's operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class WeatherDataAgent:
    def __init__(self):
        # Base URL for the Open-Meteo API
        self.base_url = "https://api.open-meteo.com/v1/forecast"

    def fetch_weather_data(self, latitude: float, longitude: float) -> dict:
        """
        Fetches weather data from the API for given latitude and longitude 
        and returns a structured dictionary with the extracted data.
        """
        # Define query parameters: current data and daily forecast
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto"
        }

        try:
            # Send request to the API
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            
            data = response.json()
            current_data = data.get("current", {})
            forecast_data = data.get("daily", {})

            # Extract specific fields into a structured format
            weather_info = {
                "current": {
                    "temperature": current_data.get("temperature_2m"),
                    "humidity": current_data.get("relative_humidity_2m"),  
                    "wind_speed": current_data.get("wind_speed_10m"),        
                    "precipitation": current_data.get("precipitation"),     
                    "weather_code": current_data.get("weather_code")        
                },
                "forecast": {
                    "max_temperature": forecast_data.get("temperature_2m_max", []),
                    "min_temperature": forecast_data.get("temperature_2m_min", []),
                    "precipitation_sum": forecast_data.get("precipitation_sum", [])
                }
            }

            logging.info(f"Successfully fetched weather data for coordinates ({latitude}, {longitude})")
            return weather_info

        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch weather data from API: {e}")
            return None
