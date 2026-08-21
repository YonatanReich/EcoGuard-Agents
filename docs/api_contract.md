# Unified Environmental Data Format (API Contract)

This document defines the unified JSON structure that all data collection agents must return. This ensures consistency across the system regardless of the external API used (e.g., Open-Meteo, geographic services, etc.).

## 1. Schema Definition

The response must be a JSON object containing the following root sections:

### 1.1 Metadata
* **`timestamp`** (String/ISO 8601): The exact time the data was collected.
* **`collection_status`** (String): The overall technical health of the fetch operation. Allowed values: `"success"`, `"partial_service_failure"`, `"failed"`.
* **`services`** (Object): Detailed status breakdown per external provider.
    * **`weather`** (Object):
        * `status` (String): `"success"` or `"failed"`.
        * `source` (String): The name of the API (e.g., "open-meteo").
    * **`geospatial`** (Object):
        * `status` (String): `"success"`, `"partial"` or `"failed"`.
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

## 2. Example JSON Response

```json
{
  "metadata": {
    "timestamp": "2026-06-21T21:18:57Z",
    "collection_status": "success",
    "services": {
      "weather": {
        "status": "success",
        "source": "open-meteo"
      },
      "geospatial": {
        "status": "partial",
        "source": "OpenStreetMap"
      }
    }
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


---

## 3. Detected Fire Event Contract

The `DetectedFireEvent` represents a fire event detected by `FireDetectionAgent`.

Unlike the general environmental data structure above, this object is
event-oriented. NASA FIRMS provides the primary satellite detection signal.
Once a thermal hotspot is detected, the event is enriched with fire-weather,
weather, and geospatial information from additional live sources.

### 3.1 Detection Flow

The fire detection process follows this sequence:

1. NASA FIRMS is queried for recent satellite thermal hotspots.
2. If no hotspots are found, the agent returns `detected: false`.
3. If hotspots are found, the most recent hotspot is selected.
4. The selected hotspot coordinates become the event location.
5. GWIS/EFFIS FWI is collected for the detected location.
6. Open-Meteo weather information is collected for the detected location.
7. OpenStreetMap geospatial context is collected around the detected location.
8. All available evidence is combined into one `DetectedFireEvent`.

The detection agent does not calculate the final operational risk score.
Final risk analysis belongs to the downstream `RiskAnalysisAgent`.

### 3.2 Core Event Fields

* **`event_type`** (String): Type of detected environmental event.
  Currently `"fire"`.

* **`detected`** (Boolean or null):
  * `true` — NASA FIRMS detected at least one thermal hotspot.
  * `false` — NASA FIRMS successfully returned zero hotspots.
  * `null` — detection could not be completed because the primary detection
    source failed.

* **`location`** (Object): Coordinates of the selected satellite hotspot when
  an event is detected. If no event is detected, contains the original search
  coordinates.

* **`detection_confidence`** (String or null): Human-readable NASA FIRMS
  confidence category for the selected VIIRS hotspot.

  Supported normalized values:
  * `"low"`
  * `"nominal"`
  * `"high"`

* **`fire_weather_severity`** (String or null): Fire-weather danger category
  derived from the GWIS/EFFIS Fire Weather Index (FWI).

  This value describes environmental conditions favorable to fire behaviour.
  It is NOT the final operational risk level of the event.

### 3.3 Satellite Evidence

The **`satellite_evidence`** object contains the NASA FIRMS evidence used for
fire detection.

Fields include:

* **`source`**: `"NASA FIRMS"`
* **`hotspots_count`**: Number of hotspots returned in the search area.
* **`selected_hotspot`**: Most recent hotspot selected as the detected event.
* **`hotspots`**: Complete list of hotspots returned by the query when an
  event is detected.

A selected hotspot may contain:

* `latitude`
* `longitude`
* `acquisition_date`
* `acquisition_time`
* `satellite`
* `instrument`
* `confidence`
* `raw_confidence`
* `normalized_confidence`
* `frp`
* `daynight`

NASA FIRMS is the primary detection source. A hotspot represents a
satellite-detected thermal anomaly and should not by itself be interpreted
as absolute proof of a wildfire.

### 3.4 Fire Danger

The **`fire_danger`** object contains fire-weather danger information from
GWIS/EFFIS.

Fields include:

* **`source`**: `"GWIS/EFFIS"`
* **`index`**: `"FWI"`
* **`latitude`**
* **`longitude`**
* **`danger_level`**
* **`fwi_min`**
* **`fwi_max`**
* **`pixel_rgb`**

Current fire-weather danger categories are:

* `low`
* `moderate`
* `high`
* `very_high`
* `extreme`
* `very_extreme`
* `unknown`

The FWI value describes fire-weather conditions and must remain conceptually
separate from the final risk score calculated by the Risk Analysis layer.

### 3.5 Weather Context

The **`weather_context`** object contains Open-Meteo weather information for
the selected hotspot location.

It follows the Weather structure defined in Section 1.4 and contains:

* Current temperature
* Relative humidity
* Wind speed
* Precipitation
* Weather code
* Daily forecast information

Weather information provides supporting environmental context and does not
independently determine whether a fire was detected.

### 3.6 Geospatial Context

The **`geospatial_context`** object follows the structure defined in
Section 1.3.

It may contain nearby:

* Roads
* Settlements
* Hospitals
* Police stations
* Fire stations
* Green areas
* Water sources

This information describes the environment and potential exposure around the
detected event.

### 3.7 Source Status

The **`source_status`** object records the status of each provider used to
construct the event.

```json
{
  "nasa_firms": "success",
  "gwis_effis": "success",
  "weather": "success",
  "geospatial": "partial"
}
```

NASA FIRMS is the primary detection source.

If NASA FIRMS fails, the system returns a failed detection rather than
incorrectly returning `detected: false`.

GWIS/EFFIS, Open-Meteo, and OpenStreetMap are enrichment sources. Failure of
one of these sources does not invalidate an existing NASA satellite
detection.

### 3.8 Example DetectedFireEvent

```json
{
  "metadata": {
    "timestamp": "2026-08-21T07:33:17Z",
    "collection_status": "success"
  },
  "event_type": "fire",
  "detected": true,
  "location": {
    "latitude": 31.91995,
    "longitude": 34.89613
  },
  "detection_confidence": "nominal",
  "fire_weather_severity": "very_high",

  "satellite_evidence": {
    "source": "NASA FIRMS",
    "hotspots_count": 1,
    "selected_hotspot": {
      "latitude": 31.91995,
      "longitude": 34.89613,
      "acquisition_date": "2026-08-21",
      "acquisition_time": "26",
      "satellite": "N20",
      "instrument": "VIIRS",
      "confidence": "n",
      "frp": 1.21,
      "daynight": "N",
      "raw_confidence": "n",
      "normalized_confidence": "nominal"
    }
  },

  "fire_danger": {
    "source": "GWIS/EFFIS",
    "index": "FWI",
    "latitude": 31.91995,
    "longitude": 34.89613,
    "danger_level": "very_high",
    "fwi_min": 38.0,
    "fwi_max": 50.0,
    "pixel_rgb": [217, 112, 16]
  },

  "weather_context": {
    "current": {
      "temperature_c": 31.3,
      "humidity_percent": 57,
      "wind_speed_kmh": 5.4,
      "precipitation_mm": 0.0,
      "weather_code": 2
    }
  },

  "geospatial_context": {
    "nearby_roads": [],
    "nearby_settlements": [],
    "nearby_hospitals": [],
    "nearby_police_stations": [],
    "nearby_fire_stations": [],
    "nearby_green_areas": [],
    "nearby_water_sources": []
  },

  "source_status": {
    "nasa_firms": "success",
    "gwis_effis": "success",
    "weather": "success",
    "geospatial": "partial"
  }
}
```

### 3.9 No Fire Detected

A successful NASA FIRMS query containing zero hotspots is represented as:

```json
{
  "metadata": {
    "timestamp": "2026-08-21T07:34:14Z",
    "collection_status": "success"
  },
  "event_type": "fire",
  "detected": false,
  "location": {
    "latitude": 29.55,
    "longitude": 34.95
  },
  "detection_confidence": null,
  "fire_weather_severity": null,
  "satellite_evidence": {
    "source": "NASA FIRMS",
    "hotspots_count": 0,
    "selected_hotspot": null
  },
  "fire_danger": null,
  "weather_context": null,
  "geospatial_context": null
}
```

This is different from a NASA FIRMS service failure. A provider failure means
that detection could not be completed, not that no fire exists.

---

## 4. Detection vs. Risk Analysis

The following concepts must remain separate across the system:

| Field | Meaning | Responsible Source/Component |
|---|---|---|
| `detected` | Whether a satellite thermal hotspot was found | NASA FIRMS / FireDetectionAgent |
| `detection_confidence` | Confidence category of the satellite detection | NASA FIRMS |
| `fire_weather_severity` | Severity of surrounding fire-weather conditions | GWIS/EFFIS FWI |
| `weather_context` | Current and forecast environmental conditions | Open-Meteo |
| `geospatial_context` | Nearby population, infrastructure and geographic context | OpenStreetMap |
| `risk_score` / `risk_level` | Overall operational risk assessment | RiskAnalysisAgent |

`FireDetectionAgent` collects and structures the evidence.

`RiskAnalysisAgent` is responsible for interpreting the detected event,
combining the available evidence with protocol-grounded analysis, and
producing the final risk assessment.