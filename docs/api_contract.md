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
2. For point-based detection, Haversine distance is calculated from the
   requested point to each returned hotspot. Hotspots outside the configured
   relevance radius are excluded.
3. If no geographically relevant hotspots remain, the agent returns
   `detected: false`.
4. If relevant hotspots remain, the most recent relevant hotspot is selected.
5. The selected hotspot coordinates become the event location.
6. GWIS/EFFIS FWI is collected for the detected location.
7. Open-Meteo weather information is collected for the detected location.
8. OpenStreetMap geospatial context is collected around the detected location.
9. All available evidence is combined into one `DetectedFireEvent`.

The detection agent does not calculate the final operational risk score.
Final risk analysis belongs to the downstream `RiskAnalysisAgent`.

### 3.2 Core Event Fields

* **`event_type`** (String): Type of detected environmental event.
  Currently `"fire"`.

* **`detected`** (Boolean or null):
  * `true` — NASA FIRMS detected at least one geographically relevant thermal
    hotspot within the configured point-detection radius.
  * `false` — NASA FIRMS successfully returned no geographically relevant
    hotspots. This includes a successful response containing only distant
    hotspots outside the configured radius.
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
* **`hotspots_count`**: Number of geographically relevant hotspots remaining
  after point-distance filtering.
* **`selected_hotspot`**: Most recent geographically relevant hotspot selected
  as the detected event.
* **`hotspots`**: Complete list of geographically relevant hotspots when an
  event is detected. Distant hotspots returned by the broader FIRMS query are
  not included as evidence for that requested point.

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

A successful NASA FIRMS query containing no geographically relevant hotspots
is represented as:

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

## 4. Detected Flood Event Contract

The `DetectedFloodEvent` represents a flood event detected by
`FloodDetectionAgent`.

Unlike the general environmental data structure above, this object is
event-oriented. Flood detection is based on combined near-real-time
precipitation and hydrological evidence rather than on a single provider or a
single hardcoded rainfall threshold.

The current detection sources are:

* Israel Meteorological Service (IMS) rainfall observations.
* Radar precipitation data. IMS Radar is preferred when programmatic access is
  available; an approved fallback provider such as RainViewer may be used. # TODO: update which radar is chosen
* Israel Water Authority / Hydrological Service observations, when recent
  water-level and/or discharge data is available.
* Existing geospatial context, when available, for spatial association and
  downstream enrichment.
### 4.1 Detection Flow

The flood detection process follows this sequence:

1. The agent receives a requested geographic location.
2. The existing IMS integration is queried for recent rainfall observations
   from geographically relevant weather stations.
3. The configured radar provider is queried for recent precipitation coverage
   around the requested area. IMS Radar is preferred when available; a
   configured fallback may be used when IMS radar access is unavailable.
4. The hydrological data source is queried for relevant river/stream monitoring
   stations and recent water-level and/or discharge observations.
5. Observation timestamps are checked so stale data is not interpreted as
   current evidence.
6. Available precipitation and hydrological evidence is geographically aligned
   with the requested area and, when available, the relevant river/catchment.
7. The agent combines the available evidence to determine whether there is
   sufficient evidence of an ongoing flood.
8. If providers return successfully but the combined evidence does not support
   an ongoing flood, the agent returns `detected: false`.
9. If the minimum evidence required for a reliable decision is unavailable due
   to provider failure, the agent returns `detected: null` rather than
   fabricating a negative result.
10. All available evidence is combined into one `DetectedFloodEvent`.

The detection agent does not calculate the final operational risk score.
Final risk analysis belongs to the downstream `RiskAnalysisAgent`.

### 4.2 Core Event Fields

* **`event_type`** (String): Type of detected environmental event.
  Currently `"flood"`.

* **`detected`** (Boolean or null):
  * `true` — the combined available evidence supports that a flood is currently
    occurring in or near the requested area.
  * `false` — the relevant detection sources were queried successfully and the
    combined evidence does not support an ongoing flood.
  * `null` — detection could not be completed reliably because the minimum
    evidence required by the implementation was unavailable due to provider
    failure.

* **`location`** (Object): The requested geographic location used for flood
  detection. When available, the object may also include the associated river
  or catchment identifier.

* **`detection_confidence`** (String or null): Normalized confidence category
  produced by `FloodDetectionAgent` from the combined available evidence.

  Supported normalized values:
  * `"low"`
  * `"nominal"`
  * `"high"`

  Unlike fire detection confidence, this value is not copied from a single
  external provider. It represents agreement, freshness, and strength of the
  available flood-detection evidence.

* **`flood_severity`** (String or null): Detection-stage estimate of the
  physical severity of the observed flood conditions.

  Supported values:
  * `"low"`
  * `"moderate"`
  * `"high"`
  * `"extreme"`
  * `"unknown"`

  `flood_severity` describes the observed event conditions and must remain
  separate from the final operational `risk_score` / `risk_level` calculated
  by `RiskAnalysisAgent`.

### 4.3 Precipitation Evidence

The **`precipitation_evidence`** object contains current precipitation evidence
used by the agent.

It may contain two provider-specific sections:

#### IMS Rainfall

The **`ims_rainfall`** object contains ground-based rainfall observations
retrieved through the existing IMS integration.

Fields include:

* **`source`**: `"IMS"`
* **`stations_count`**: Number of geographically relevant stations with usable
  recent rainfall observations.
* **`observations`**: Array of relevant station observations.

Each station observation may contain:

* `station_id`
* `station_name`
* `latitude`
* `longitude`
* `observation_time`
* `precipitation_mm`
* `measurement_interval_minutes`
* `distance_from_requested_location_km`

The original observation timestamp must be preserved. Missing rainfall values
must not be converted to zero unless the source explicitly reports a valid zero
measurement.

#### Radar #TODO: update this part once i have radar data

The **`radar`** object contains spatial precipitation evidence from the
configured radar provider.

Fields may include:

* **`source`**: Provider name, for example `"IMS Radar"` or `"RainViewer"`.
* **`observation_time`**: Timestamp of the radar frame used for detection.
* **`provider`**: Concrete radar provider used for this request.
* **`available`**: Whether a usable radar observation was available.
* **`precipitation_intensity_mm_h`**: Quantitative precipitation intensity when
  exposed by the provider or derived by the approved radar adapter.
* **`intensity_category`**: Optional normalized intensity category when a
  quantitative value is unavailable.
* **`coverage`**: Optional geographic coverage/bounding information for the
  radar observation.

The flood agent consumes a normalized radar representation and must not depend
on provider-specific response formats.

### 4.4 Hydrological Evidence

The **`hydrological_evidence`** object contains available river/stream response
information from the Israel Water Authority / Hydrological Service.

Fields include:

* **`source`**: `"Israel Water Authority"`
* **`stations_count`**: Number of geographically relevant hydrological stations
  with usable observations.
* **`selected_station`**: Most relevant station used as hydrological evidence,
  when available.
* **`stations`**: Optional list of all geographically relevant stations used by
  the detector.

A hydrological station observation may contain:

* `station_id`
* `station_name`
* `river_name`
* `latitude`
* `longitude`
* `observation_time`
* `water_level_m`
* `discharge_m3_s`
* `water_level_change_m`
* `discharge_change_m3_s`
* `change_interval_minutes`

Change fields are included only when enough recent observations exist to
calculate them. Missing real-time hydrological measurements must remain `null`
or unavailable; historical measurements must not be presented as current
observations.

Hydrological evidence is the most direct evidence of river response when it is
available. However, lack of a hydrological station at a location does not by
itself mean that no flood exists.

### 4.5 Geospatial Context

The **`geospatial_context`** object follows the structure defined in Section
1.3 when geospatial enrichment is requested.

It may contain nearby:

* Roads
* Settlements
* Hospitals
* Police stations
* Fire stations
* Green areas
* Water sources

For flood detection, geospatial information may also be used to associate the
requested location and observations with a nearby river or drainage area when
such information is available.

Geospatial context provides supporting spatial information and does not
independently determine whether a flood was detected.

### 4.6 Source Status

The **`source_status`** object records the status of each provider used to
construct the event.

Recommended status values are:

* `"success"` — provider returned usable observations.
* `"partial"` — provider returned usable but incomplete observations.
* `"no_data"` — provider request succeeded but no relevant/current observation
  was available.
* `"failed"` — provider could not be queried successfully.

Example:

```json
{
  "ims_rainfall": "success",
  "radar": "success",
  "hydrological": "partial",
  "geospatial": "success"
}
```

Flood detection does not assume that one provider is always the sole primary
source. The agent combines the available evidence and records provider
availability explicitly.

Failure of one source does not automatically invalidate a flood detection when
other sufficiently strong evidence is available. Conversely, provider failure
must not be interpreted as evidence that no flood exists.

### 4.7 Example DetectedFloodEvent

```json
{
  "metadata": {
    "timestamp": "2026-01-18T08:42:00Z",
    "collection_status": "success"
  },
  "event_type": "flood",
  "detected": true,
  "location": {
    "latitude": 31.15,
    "longitude": 35.36,
    "river_name": "example_stream",
    "catchment_id": "example_catchment"
  },
  "detection_confidence": "high",
  "flood_severity": "high",

  "precipitation_evidence": {
    "ims_rainfall": {
      "source": "IMS",
      "stations_count": 2,
      "observations": [
        {
          "station_id": "IMS-EXAMPLE-001",
          "station_name": "Example Rain Station",
          "latitude": 31.18,
          "longitude": 35.32,
          "observation_time": "2026-01-18T08:40:00Z",
          "precipitation_mm": 8.4,
          "measurement_interval_minutes": 10,
          "distance_from_requested_location_km": 5.8
        }
      ]
    },
    "radar": {
      "source": "RainViewer",
      "provider": "RainViewer",
      "observation_time": "2026-01-18T08:40:00Z",
      "available": true,
      "precipitation_intensity_mm_h": 34.2,
      "intensity_category": "high"
    }
  },

  "hydrological_evidence": {
    "source": "Israel Water Authority",
    "stations_count": 1,
    "selected_station": {
      "station_id": "HYDRO-EXAMPLE-001",
      "station_name": "Example Hydrological Station",
      "river_name": "example_stream",
      "latitude": 31.14,
      "longitude": 35.35,
      "observation_time": "2026-01-18T08:40:00Z",
      "water_level_m": 2.18,
      "discharge_m3_s": 42.7,
      "water_level_change_m": 0.64,
      "discharge_change_m3_s": 18.5,
      "change_interval_minutes": 20
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
    "ims_rainfall": "success",
    "radar": "success",
    "hydrological": "success",
    "geospatial": "success"
  }
}
```

The IDs and numeric values in this example are illustrative and do not
represent a specific real event.

### 4.8 No Flood Detected

A successful flood-detection cycle in which the available current evidence does
not support an ongoing flood is represented as:

```json
{
  "metadata": {
    "timestamp": "2026-01-18T10:10:00Z",
    "collection_status": "success"
  },
  "event_type": "flood",
  "detected": false,
  "location": {
    "latitude": 31.78,
    "longitude": 35.22
  },
  "detection_confidence": null,
  "flood_severity": null,
  "precipitation_evidence": {
    "ims_rainfall": {
      "source": "IMS",
      "stations_count": 1,
      "observations": [
        {
          "station_id": "IMS-EXAMPLE-002",
          "observation_time": "2026-01-18T10:10:00Z",
          "precipitation_mm": 0.0,
          "measurement_interval_minutes": 10
        }
      ]
    },
    "radar": {
      "source": "IMS Radar",
      "provider": "IMS Radar",
      "observation_time": "2026-01-18T10:05:00Z",
      "available": true,
      "precipitation_intensity_mm_h": 0.0,
      "intensity_category": "none"
    }
  },
  "hydrological_evidence": {
    "source": "Israel Water Authority",
    "stations_count": 1,
    "selected_station": {
      "station_id": "HYDRO-EXAMPLE-002",
      "observation_time": "2026-01-18T10:00:00Z",
      "water_level_m": 0.31,
      "discharge_m3_s": 0.8
    }
  },
  "geospatial_context": null,
  "source_status": {
    "ims_rainfall": "success",
    "radar": "success",
    "hydrological": "success",
    "geospatial": "no_data"
  }
}
```

This is different from a provider failure. If the data required to make a
reliable detection decision cannot be obtained, the agent should return
`detected: null` with the relevant provider marked as `"failed"`, rather than
incorrectly returning `detected: false`.


---

## 5. Detection vs. Risk Analysis

The following concepts must remain separate across the system:

| Field | Meaning | Responsible Source/Component |
|---|---|---|
| `DetectedFireEvent.detected` | Whether a geographically relevant satellite thermal hotspot was found | NASA FIRMS / FireDetectionAgent |
| `DetectedFireEvent.detection_confidence` | Confidence category of the satellite fire detection | NASA FIRMS |
| `fire_weather_severity` | Severity of surrounding fire-weather conditions | GWIS/EFFIS FWI |
| `DetectedFloodEvent.detected` | Whether combined current precipitation and hydrological evidence supports an ongoing flood | FloodDetectionAgent |
| `DetectedFloodEvent.detection_confidence` | Confidence in the flood-detection decision based on the available evidence | FloodDetectionAgent |
| `flood_severity` | Detection-stage estimate of the physical severity of observed flood conditions | FloodDetectionAgent |
| `precipitation_evidence` | Current ground/radar precipitation evidence used for flood detection | IMS / Radar provider |
| `hydrological_evidence` | Current water-level/discharge evidence used for flood detection | Israel Water Authority / Hydrological Service |
| `weather_context` | Current and forecast environmental conditions used as fire-event context | Open-Meteo |
| `geospatial_context` | Nearby population, infrastructure and geographic context | OpenStreetMap / configured geospatial provider |
| `risk_score` / `risk_level` | Overall operational risk assessment | RiskAnalysisAgent |

`FireDetectionAgent` and `FloodDetectionAgent` collect and structure the
available event evidence.

`RiskAnalysisAgent` is responsible for interpreting a detected event, combining
the available evidence with protocol-grounded analysis, and producing the final
operational risk assessment.

