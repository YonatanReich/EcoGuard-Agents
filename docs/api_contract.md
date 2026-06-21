# Unified Environmental Data Format (API Contract)

This document defines the unified JSON structure that all data collection agents must return. This ensures consistency across the system regardless of the external API used (e.g., Open-Meteo, geographic services, etc.).

## 1. Schema Definition

The response must be a JSON object containing the following root sections:

### 1.1 Metadata
* **`timestamp`** (String/ISO 8601): The exact time the data was collected.
* **`data_source`** (String): The name of the external API or source (e.g., "open-meteo", "israel-gov-data").
* **`collection_status`** (String): The status of the fetch operation. Allowed values: `"success"`, `"failed"`, `"partial"`.

### 1.2 Location
* **`latitude`** (Float): Geographical latitude.
* **`longitude`** (Float): Geographical longitude.

### 1.3 Geospatial Context
* **`terrain_type`** (String): Type of land (e.g., "urban", "forest", "desert").
* **`vegetation_density`** (Float): A normalized score (0.0 to 1.0) indicating vegetation coverage.
* **`distance_to_water_m`** (Float): Distance to the nearest significant water body in meters.

### 1.4 Weather
* **`current`** (Object):
    * `temperature_c` (Float): Current temperature in Celsius.
    * `humidity_percent` (Float): Relative humidity percentage.
    * `wind_speed_kmh` (Float): Wind speed in kilometers per hour.
    * `precipitation_mm` (Float): Current precipitation in millimeters.
    * `weather_code` (Integer): Standardized WMO weather code.

### 1.5 Forecast
* **`daily`** (Object):
    * `max_temp_c` (Array of Floats): Max temperatures for the upcoming days.
    * `min_temp_c` (Array of Floats): Min temperatures for the upcoming days.
    * `max_wind_speed_kmh`** (Array of Floats): Maximum wind speeds for the upcoming days.
    * `precipitation_sum_mm` (Array of Floats): Total expected precipitation per day.

---

## 2. Example JSON Response (Covers EA-128)

```json
{
  "metadata": {
    "timestamp": "2026-06-21T21:18:57Z",
    "data_source": "open-meteo",
    "collection_status": "success"
  },
  "location": {
    "latitude": 31.783333,
    "longitude": 35.216667
  },
  "geospatial_context": {
    "terrain_type": "urban",
    "vegetation_density": 0.3,
    "distance_to_water_m": 45000.0
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