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
hydrological and precipitation evidence, with catchment-aware geographic
mapping. It must not rely on a single hardcoded rainfall threshold.

The current flood-detection sources are:

* **Israel Hydrological Service API** (`hydro.water.gov.il`) for current/recent
  river and stream observations such as water level and/or discharge, when
  available.
* **Israel Meteorological Service (IMS)** for recent ground-based rainfall
  observations. This requires a new full IMS integration for the flood pipeline;
  the system's existing Open-Meteo weather integration is not the IMS
  integration and must not be treated as a replacement for it.
* **Radar precipitation data** for spatial precipitation coverage. IMS Radar is
  preferred when programmatic access is available; a configured fallback such
  as RainViewer may be used if required.
* **GovMap drainage basins** (`opendata:Nikuz`) for catchment mapping. The layer
  is downloaded from the GovMap WFS and stored locally as GeoJSON in
  `EPSG:4326` for runtime point-in-polygon lookup.

### 4.1 Detection Flow

The flood detection process follows this sequence:

1. The agent receives a requested geographic location (`latitude`,
   `longitude`).
2. The locally stored GovMap `opendata:Nikuz` layer is queried using
   point-in-polygon lookup to identify the drainage basin containing the
   requested point.
3. The identified catchment is used to support selection of relevant
   hydrological stations and to spatially scope precipitation evidence.
4. The Israel Hydrological Service API is queried for current/recent
   observations from relevant hydrometric stations.
5. The dedicated IMS rainfall integration is queried for recent rainfall
   observations from geographically relevant IMS stations.
6. The configured radar provider is queried for recent spatial precipitation
   coverage over the requested area/catchment when radar data is available.
7. Observation timestamps are checked so stale data is not interpreted as
   current evidence.
8. Available hydrological, rainfall, and radar evidence is aligned with the
   requested location and drainage basin.
9. The agent combines the available evidence to determine whether there is
   sufficient evidence of an ongoing flood.
10. If the required providers return successfully but the evidence does not
    support an ongoing flood, the agent returns `detected: false`.
11. If the minimum evidence required for a reliable decision is unavailable due
    to provider failure, the agent returns `detected: null` rather than
    fabricating a negative result.
12. All available evidence is combined into one `DetectedFloodEvent`.

The detection agent does not calculate the final operational risk score.
Final risk analysis belongs to the downstream `RiskAnalysisAgent`.

### 4.2 Core Event Fields

* **`event_type`** (String): Type of detected environmental event.
  Currently `"flood"`.

* **`detected`** (Boolean or null):
  * `true` — the combined available evidence supports that a flood is currently
    occurring in or near the requested area.
  * `false` — the minimum required sources were queried successfully and the
    available evidence does not support an ongoing flood.
  * `null` — detection could not be completed reliably because the minimum
    evidence required by the implementation was unavailable due to provider
    failure.

* **`location`** (Object): The original geographic location supplied to the
  detector.
  * `latitude`
  * `longitude`

* **`detection_confidence`** (String or null): Normalized confidence category
  produced by `FloodDetectionAgent` from the combined available evidence.

  Supported normalized values:
  * `"low"`
  * `"nominal"`
  * `"high"`

  Unlike fire detection confidence, this value is not copied from a single
  external provider. It represents the strength, freshness, and agreement of
  the available flood-detection evidence.

* **`flood_severity`** (String or null): Detection-stage estimate of the
  physical severity of the observed flood conditions.

  Supported values:
  * `"low"`
  * `"moderate"`
  * `"high"`
  * `"extreme"`
  * `"unknown"`

  `flood_severity` describes observed physical conditions and must remain
  separate from the final operational `risk_score` / `risk_level` calculated
  by `RiskAnalysisAgent`.

### 4.3 IMS Rainfall Evidence

The **`ims_rainfall`** object contains recent ground-based rainfall
observations retrieved from the Israel Meteorological Service.

This is a **new dedicated flood data integration**. The existing Open-Meteo
weather integration remains the provider for the generic `weather_context`
used elsewhere in the system and must not be used as a substitute for IMS
rainfall evidence.

Fields include:

* **`source`**: `"Israel Meteorological Service (IMS)"`
* **`stations_count`**: Number of geographically relevant IMS stations with
  usable recent rainfall observations.
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

The original IMS observation timestamp must be preserved. Missing rainfall
values must not be converted to zero unless IMS explicitly reports a valid zero
measurement.

### 4.4 Radar Evidence

The **`radar_evidence`** object contains recent spatial precipitation evidence
from the configured radar provider.

Fields may include:

* **`source`**: Provider name, for example `"IMS Radar"` or `"RainViewer"`.
* **`provider`**: Concrete radar provider used for the request.
* **`observation_time`**: Timestamp of the radar frame used for detection.
* **`available`**: Whether a usable radar observation was available.
* **`precipitation_intensity_mm_h`**: Quantitative precipitation intensity when
  exposed by the provider or derived by the approved radar adapter.
* **`intensity_category`**: Optional normalized intensity category when a
  quantitative value is unavailable.
* **`coverage`**: Optional geographic coverage/bounding information for the
  radar observation.

The flood agent consumes a normalized radar representation and must not depend
on provider-specific response formats.

Radar is supporting spatial precipitation evidence. The exact production radar
provider may be changed without changing the `DetectedFloodEvent` contract.

### 4.5 Hydrological Evidence

The **`hydrological_evidence`** object contains current/recent river or stream
observations from the official Israel Hydrological Service API.

Fields include:

* **`source`**: `"Israel Hydrological Service"`
* **`provider`**: `"Israel Water Authority"`
* **`stations_count`**: Number of geographically relevant hydrometric stations
  with usable current/recent observations.
* **`selected_station`**: Most relevant station used as hydrological evidence,
  when available.
* **`stations`**: Optional list of all geographically relevant stations used by
  the detector.

A hydrological station observation may contain, according to API availability:

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
calculate them. Missing live measurements must remain `null` or unavailable;
historical measurements must never be presented as current observations.

Hydrological observations are the most direct available evidence of actual
river response. However, absence of a relevant hydrometric station does not by
itself prove that no flood exists.

### 4.6 Catchment Context

The **`catchment_context`** object contains the drainage-basin mapping used by
`FloodDetectionAgent`.

The source is the official GovMap WFS drainage-basin layer:

* **WFS layer**: `opendata:Nikuz`
* **Feature type**: `WATER_BASIN`
* **Native CRS**: `EPSG:2039`
* **Runtime/local GeoJSON CRS**: `EPSG:4326`

The layer is static geographic data. It should be downloaded and cached/stored
locally rather than fetched from GovMap for every flood-detection request.

At runtime, the requested longitude/latitude is matched to a basin polygon
using point-in-polygon lookup.

The event should include the identifying attributes required downstream, not
the full basin polygon geometry.

Fields include:

* **`source`**: `"GovMap"`
* **`layer`**: `"opendata:Nikuz"`
* **`unique_id`**: Value from GovMap `UNIQ_ID`.
* **`basin_code`**: Value from GovMap `BASIN_CODE`.
* **`basin_name`**: Value from GovMap `FNAME`.
* **`drain_to`**: Value from GovMap `DRAIN_TO`, when present.
* **`to_basin`**: Value from GovMap `TO_BASIN`, when present.
* **`area_m2`**: Value from GovMap `ORIG_AREA`.
* **`data_year`**: Value from GovMap `DATA_YEAR`, when present.
* **`product_version`**: Value from GovMap `PRDCT_VER`, when present.

If the requested point cannot be associated with a basin, the catchment lookup
must return `no_data` rather than fabricating a basin assignment.

### 4.7 Optional Geospatial Enrichment

The **`geospatial_context`** object follows the structure defined in Section
1.3 when OpenStreetMap enrichment is requested.

It may contain nearby:

* Roads
* Settlements
* Hospitals
* Police stations
* Fire stations
* Green areas
* Water sources

This OpenStreetMap-derived context is distinct from `catchment_context`.
OpenStreetMap is used for operational/geographic enrichment; GovMap is used for
drainage-basin mapping.

### 4.8 Source Status

The **`source_status`** object records the status of each source used to
construct the flood event.

Recommended status values are:

* `"success"` — source returned usable data.
* `"partial"` — source returned usable but incomplete data.
* `"no_data"` — source access succeeded but no relevant/current data was
  available.
* `"failed"` — source could not be queried or loaded successfully.

Example:

```json
{
  "ims_rainfall": "success",
  "radar": "success",
  "hydrological_service": "success",
  "catchment": "success",
  "geospatial": "partial"
}
```

The hydrological source is the most direct current-event evidence when a
relevant station is available. IMS rainfall and radar provide supporting
precipitation evidence and improve coverage when direct hydrological
measurements are incomplete or unavailable.

Failure of one supporting source does not automatically invalidate a flood
detection when other sufficiently strong evidence is available. Conversely,
provider failure must not be interpreted as evidence that no flood exists.

### 4.9 Example DetectedFloodEvent

```json
{
  "metadata": {
    "timestamp": "2026-01-18T08:42:00Z",
    "collection_status": "success"
  },
  "event_type": "flood",
  "detected": true,
  "location": {
    "latitude": 32.50,
    "longitude": 35.50
  },
  "detection_confidence": "high",
  "flood_severity": "high",

  "catchment_context": {
    "source": "GovMap",
    "layer": "opendata:Nikuz",
    "unique_id": 64845678,
    "basin_code": 18,
    "basin_name": "בית שאן - בזק",
    "drain_to": 21,
    "to_basin": 44,
    "area_m2": 214626431.176,
    "data_year": 2021,
    "product_version": "2021-06"
  },

  "ims_rainfall": {
    "source": "Israel Meteorological Service (IMS)",
    "stations_count": 2,
    "observations": [
      {
        "station_id": "IMS-EXAMPLE-001",
        "station_name": "Example Rain Station",
        "latitude": 32.48,
        "longitude": 35.46,
        "observation_time": "2026-01-18T08:40:00Z",
        "precipitation_mm": 8.4,
        "measurement_interval_minutes": 10,
        "distance_from_requested_location_km": 4.8
      }
    ]
  },

  "radar_evidence": {
    "source": "RainViewer",
    "provider": "RainViewer",
    "observation_time": "2026-01-18T08:40:00Z",
    "available": true,
    "precipitation_intensity_mm_h": 34.2,
    "intensity_category": "high"
  },

  "hydrological_evidence": {
    "source": "Israel Hydrological Service",
    "provider": "Israel Water Authority",
    "stations_count": 1,
    "selected_station": {
      "station_id": "HYDRO-EXAMPLE-001",
      "station_name": "Example Hydrometric Station",
      "river_name": "example_stream",
      "latitude": 32.49,
      "longitude": 35.51,
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
    "hydrological_service": "success",
    "catchment": "success",
    "geospatial": "partial"
  }
}
```

The IDs and numeric values in this example are illustrative and do not
represent a specific real flood event. The GovMap field names and example
values reflect the current `opendata:Nikuz` schema observed during integration.

### 4.10 No Flood Detected

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

  "catchment_context": {
    "source": "GovMap",
    "layer": "opendata:Nikuz",
    "unique_id": 64845678,
    "basin_code": 18,
    "basin_name": "בית שאן - בזק",
    "drain_to": 21,
    "to_basin": 44,
    "area_m2": 214626431.176,
    "data_year": 2021,
    "product_version": "2021-06"
  },

  "ims_rainfall": {
    "source": "Israel Meteorological Service (IMS)",
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

  "radar_evidence": {
    "source": "IMS Radar",
    "provider": "IMS Radar",
    "observation_time": "2026-01-18T10:05:00Z",
    "available": true,
    "precipitation_intensity_mm_h": 0.0,
    "intensity_category": "none"
  },

  "hydrological_evidence": {
    "source": "Israel Hydrological Service",
    "provider": "Israel Water Authority",
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
    "hydrological_service": "success",
    "catchment": "success",
    "geospatial": "no_data"
  }
}
```

This is different from a source failure. If the data required to make a
reliable detection decision cannot be obtained, the agent should return
`detected: null` with the relevant source marked as `"failed"`, rather than
incorrectly returning `detected: false`.

---


## 5. Detection vs. Risk Analysis

The following concepts must remain separate across the system:

| Field | Meaning | Responsible Source/Component |
|---|---|---|
| `DetectedFireEvent.detected` | Whether a geographically relevant satellite thermal hotspot was found | NASA FIRMS / FireDetectionAgent |
| `DetectedFireEvent.detection_confidence` | Confidence category of the satellite fire detection | NASA FIRMS |
| `fire_weather_severity` | Severity of surrounding fire-weather conditions | GWIS/EFFIS FWI |
| `DetectedFloodEvent.detected` | Whether current hydrological and precipitation evidence supports an ongoing flood | FloodDetectionAgent |
| `DetectedFloodEvent.detection_confidence` | Confidence in the flood-detection decision based on evidence strength, freshness, and agreement | FloodDetectionAgent |
| `flood_severity` | Detection-stage estimate of the physical severity of observed flood conditions | FloodDetectionAgent |
| `ims_rainfall` | Current/recent ground-based rainfall observations used by flood detection | Israel Meteorological Service (IMS) |
| `radar_evidence` | Current spatial precipitation evidence used by flood detection | Configured radar provider (IMS Radar preferred; fallback may be used) |
| `hydrological_evidence` | Current/recent water-level and/or discharge evidence | Israel Hydrological Service API / Israel Water Authority |
| `catchment_context` | Drainage-basin association for the requested location | GovMap `opendata:Nikuz` |
| `weather_context` | Generic current and forecast weather context currently used by the system | Open-Meteo |
| `geospatial_context` | Nearby population, infrastructure, and geographic enrichment | OpenStreetMap |
| `risk_score` / `risk_level` | Overall operational risk assessment | RiskAnalysisAgent |

`FireDetectionAgent` and `FloodDetectionAgent` collect and structure the
available event evidence.

`RiskAnalysisAgent` is responsible for interpreting a detected event, combining
the available evidence with protocol-grounded analysis, and producing the final
operational risk assessment.
