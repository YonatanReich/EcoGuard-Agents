"""
Weather Data Agent

Serves the latest stored weather observation for a single coordinate.

It used to call Open-Meteo itself, once per HTTP request. That made it the
third independent caller of the same API - alongside the scheduled collector
and the fire-risk model's private cache - each with its own rate-limiter state
that could not see the others, and it put a multi-second provider round trip on
the hot path of an endpoint that was already slow.

Now the collection layer is the only thing that talks to Open-Meteo, and this
reads what it wrote. The response shape is unchanged, so nothing downstream had
to move. Two things did change, and both are visible in the response:

  * a coordinate is answered by the 5 km grid cell containing it, so
    metadata.observation reports which cell, how far away it is, and when the
    reading was taken
  * weather.forecast.daily is empty. The store holds observations; a forecast
    is not one, and inventing the key's contents would be worse than an honest
    absence.

The agent never raises. On any failure it returns the same structure with
metadata.collection_status set to "failed", so callers can merge results from
several agents without special-casing errors.

Consumed by: backend.main.get_environmental_data, agents.fire_detection_agent
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from ecoguard.database.repositories.weather_history import (
    CURRENT_MAX_AGE_HOURS,
    current_for_point,
)

# Configure logging to easily track the agent's operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class WeatherDataAgent:
    """
    Reads the latest stored observation for a coordinate.

    Attributes:
        source_name (str): Provider label copied into metadata.data_source.
            Still open-meteo - that is who measured it; only the path from
            them to here changed.
    """

    def __init__(self):
        self.source_name = "open-meteo"

    def build_failed_response(
        self,
        latitude: float,
        longitude: float,
        timestamp: str,
        error: str,
    ) -> dict:
        """Return unavailable weather data without inventing observations."""
        return {
            "metadata": {
                "timestamp": timestamp,
                "data_source": self.source_name,
                "collection_status": "failed",
            },
            "location": {
                "latitude": latitude,
                "longitude": longitude,
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
                "nearby_water_sources": [],
            },
            "weather": {"current": {}, "forecast": {"daily": {}}},
            "error": error,
        }

    def fetch_weather_data(self, latitude: float, longitude: float) -> dict:
        """
        Return the newest stored reading for the grid cell holding a coordinate.

        Args:
            latitude (float): Location latitude in decimal degrees.
            longitude (float): Location longitude in decimal degrees.

        Returns:
            dict: Unified environmental record containing:
                - metadata: timestamp, data_source, collection_status
                  ("success" or "failed"), and on success an `observation`
                  block naming the cell the answer came from, its distance in
                  metres, and when the reading was taken.
                - location: the coordinates that were requested.
                - geospatial_context: always empty here. This agent does not
                  produce geospatial data, but the key is present so the shape
                  matches GeospatialContextAgent's output and the two can be
                  merged without key checks.
                - weather.current: temperature_c, humidity_percent,
                  wind_speed_kmh, precipitation_mm, weather_code.
                - weather.forecast.daily: empty. The store holds observations,
                  and a forecast is not one.

            On failure the same shape is returned with collection_status
            "failed" and empty weather sections. No exception propagates.
        """
        current_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            reading = current_for_point(latitude, longitude)
        except SQLAlchemyError:
            logging.error("Weather store unreachable for (%s, %s)", latitude, longitude)
            return self.build_failed_response(
                latitude=latitude, longitude=longitude,
                timestamp=current_timestamp, error="observation store unavailable",
            )
        except Exception:
            logging.exception("Unexpected error reading weather for (%s, %s)", latitude, longitude)
            return self.build_failed_response(
                latitude=latitude, longitude=longitude,
                timestamp=current_timestamp, error="unexpected store error",
            )

        # Outside the collected grid, or collection has been down long enough
        # that nothing recent exists. Either way there is no observation, and
        # saying so is the point of the failed response.
        if reading is None:
            logging.warning(
                "No weather observation within %s hours near (%s, %s)",
                CURRENT_MAX_AGE_HOURS, latitude, longitude,
            )
            return self.build_failed_response(
                latitude=latitude, longitude=longitude,
                timestamp=current_timestamp, error="no recent observation for this location",
            )

        weather_code = reading.get("weather_code")

        unified_data = {
            "metadata": {
                "timestamp": current_timestamp,
                "data_source": self.source_name,
                "collection_status": "success",
                # A point question answered by a grid. A caller that cares
                # whether it is looking at the exact coordinate or the cell
                # centre 3 km away can see which.
                "observation": {
                    "cell_id": reading["cell_id"],
                    "observed_at": reading["observed_at"].isoformat(),
                    "cell_latitude": reading["latitude"],
                    "cell_longitude": reading["longitude"],
                    "distance_m": reading["distance_m"],
                },
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
                    "temperature_c": reading.get("temperature_2m"),
                    "humidity_percent": reading.get("relative_humidity_2m"),
                    "wind_speed_kmh": reading.get("wind_speed_10m"),
                    "precipitation_mm": reading.get("precipitation"),
                    # Stored as a float because every hourly value shares one
                    # numeric column; the WMO code is an integer.
                    "weather_code": None if weather_code is None else int(weather_code),
                },
                "forecast": {"daily": {}}
            }
        }

        logging.info(
            "Served stored weather for (%s, %s) from cell %s, %.0f m away",
            latitude, longitude, reading["cell_id"], reading["distance_m"],
        )
        return unified_data
