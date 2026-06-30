# Unified Environmental Data Format (API Contract)

This document defines the unified JSON structure that all data collection agents must return. This ensures consistency across the system regardless of the external API used (e.g., Open-Meteo, geographic services, etc.).

## 1. Schema Definition

The response must be a JSON object containing the following root sections:

### 1.1 Metadata
* **`timestamp`** (String/ISO 8601): The exact time the data was collected.
* **`system_status`** (String): The overall technical health of the fetch operation. Allowed values: `"success"`, `"partial_service_failure"`, `"failure"`.
* **`services`** (Object): Detailed status breakdown per external provider.
    * **`weather`** (Object):
        * `status` (String): `"success"` or `"failure"`.
        * `source` (String): The name of the API (e.g., "open-meteo").
    * **`geospatial`** (Object):
        * `status` (String): `"success"`, `"partial"` or `"failure"`.
        * `source` (String): The name of the API (e.g., "OpenStreetMap").

### 1.2 Location
* **`latitude`** (Float): Geographical latitude.
* **`longitude`** (Float): Geographical longitude.

### 1.3 Geospatial Context
* **`terrain_type`** (String): Type of land (e.g., "urban", "forest", "desert").
* **`region_type`** (String): Administrative or geographical region classification.
* **`vegetation_density`** (Float): A normalized score (0.0 to 1.0) indicating vegetation coverage (relevant for fire risk).
* **`distance_to_water_m`** (Float): Distance to the nearest significant water body in meters (relevant for flood risk).
* **`nearby_roads`** (Array of Objects): Unique nearby roads and highways.
* **`nearby_settlements`** (Array of Objects): Nearby populated areas (cities, towns, etc.).
* **`nearby_hospitals`** (Array of Objects): Nearby medical facilities.
* **`nearby_police_stations`** (Array of Objects): Nearby police stations.
* **`nearby_fire_stations`** (Array of Objects): Nearby fire stations.
* **`nearby_green_areas`** (Array of Objects): Nearby forests, parks, or nature reserves.
* **`nearby_water_sources`** (Array of Objects): Nearby lakes, rivers, or sea access points.

### 1.4 Weather
* **`current`** (Object):
    * `temperature_c` (Float): Current temperature in Celsius.
    * `humidity_percent` (Float): Relative humidity percentage.
    * `wind_speed_kmh` (Float): Wind speed in kilometers per hour.
    * `precipitation_mm` (Float): Current precipitation in millimeters.
    * `weather_code` (Integer): Standardized WMO weather code.

* **`forecast`** (Object):
    * **`daily`** (Object):
        * `max_temp_c` (Array of Floats): Max temperatures for the upcoming days.
        * `min_temp_c` (Array of Floats): Min temperatures for the upcoming days.
        * `max_wind_speed_kmh` (Array of Floats): Maximum wind speeds for the upcoming days.
        * `precipitation_sum_mm` (Array of Floats): Total expected precipitation per day.

---

## 2. Example JSON Response (Covers EA-128)

```json
{
  "metadata": {
    "timestamp": "2026-06-21T21:18:57Z",
    "system_status": "success",
    "services": {
      "weather": {
        "status": "success",
        "source": "open-meteo"
      },
      "geospatial": {
        "status": "partial",
        "source": "OpenStreetMap",
      }
    }
  },
  },
  "location": {
    "latitude": 31.783333,
    "longitude": 35.216667
  },
"geospatial_context": {
    "terrain_type": "urban",
    "region_type": "metropolitan",
    "vegetation_density": 0.3,
    "distance_to_water_m": 45000.0,
    "nearby_roads": [],
    "nearby_settlements": [],
    "nearby_hospitals": [],
    "nearby_police_stations": [],
    "nearby_fire_stations": [
      {
        "name": "Jerusalem Central Fire Station",
        "type": "fire_station",
        "latitude": 31.784,
        "longitude": 35.211
      }
    ],
    "nearby_green_areas": [],
    "nearby_water_sources": []
  },
  "weather": {
    "current": {
      "temperature_c": 19.5,
      "humidity_percent": 74.0,
      "wind_speed_kmh": 9.8,
      "precipitation_mm": 0.0,
      "weather_code": 0
    },
    "forecast": {
      "daily": {
        "max_temp_c": [28.7, 27.0, 27.1, 28.7, 28.0, 27.6, 28.6],
        "min_temp_c": [18.2, 17.5, 17.8, 18.0, 18.5, 17.9, 18.1],
        "max_wind_speed_kmh": [12.5, 24.1, 18.0, 11.2, 9.5, 14.2, 22.0],
        "precipitation_sum_mm": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
      }
    }
  }
}