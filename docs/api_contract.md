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

> **Not yet populated.** The first four fields below, together with
> `nearby_green_areas` and `nearby_water_sources`, are part of the intended
> contract but are hardcoded to `null` / `[]` by the current
> `GeospatialContextAgent`. They are documented here as the target shape.
> Downstream consumers, including `RiskAnalysisAgent`, must not build logic on
> them and must not treat their absence as meaningful — it reflects a
> limitation of the collection layer, not a property of any given location.
> Only `nearby_roads`, `nearby_settlements`, `nearby_hospitals`,
> `nearby_police_stations` and `nearby_fire_stations` carry real data today.

* **`terrain_type`** (String): Type of land (e.g., "urban", "forest", "desert"). *Not yet populated.*
* **`region_type`** (String): Administrative or geographical region classification. *Not yet populated.*
* **`vegetation_density`** (Float): A normalized score (0.0 to 1.0) indicating vegetation coverage (relevant for fire risk). *Not yet populated.*
* **`distance_to_water_m`** (Float): Distance to the nearest significant water body in meters (relevant for flood risk). *Not yet populated.*
* **`nearby_roads`** (Array of Objects): Unique nearby roads and highways.
* **`nearby_settlements`** (Array of Objects): Nearby populated areas (cities, towns, etc.).
* **`nearby_hospitals`** (Array of Objects): Nearby medical facilities.
* **`nearby_police_stations`** (Array of Objects): Nearby police stations.
* **`nearby_fire_stations`** (Array of Objects): Nearby fire stations.
* **`nearby_green_areas`** (Array of Objects): Nearby forests, parks, or nature reserves.
* **`nearby_water_sources`** (Array of Objects): Nearby lakes, rivers, or sea access points.

### 1.4 Weather

Read from the collection layer's stored observations, not fetched per request.
The coordinate is answered by the 5 km grid cell containing it; see
`metadata.services.weather.observation` for which cell, how far away, and when
the reading was taken. A coordinate with no cell within 5 km carrying a reading
under 6 hours old gets `collection_status: "failed"` and an empty `current`.

* **`current`** (Object):
    * `temperature_c` (Float): Temperature in Celsius at the reading's hour.
    * `humidity_percent` (Float): Relative humidity percentage.
    * `wind_speed_kmh` (Float): Wind speed in kilometers per hour.
    * `precipitation_mm` (Float): Precipitation in millimeters for that hour.
    * `weather_code` (Integer): Standardized WMO weather code.

  Any individual value may be `null` where the provider reported none. A null
  is "not known" and is never defaulted to zero.

* **`forecast`** (Object):
    * **`daily`** (Object): **Always empty.** The store holds observations and
      a forecast is not one. The key is retained so the response shape is
      stable for callers that index into it.

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
      "daily": {}
    }
  }
}
```


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

---

## 5. Risk Assessment and Response Plan Contract

`RiskAnalysisAgent` consumes a `DetectedFireEvent` and produces a
`RiskAssessment`. `ResponsePlanningAgent` consumes both and produces a
`ResponsePlan`. Both reason with a Claude model and both are grounded in a
committed corpus of fire response protocols (`data/protocols/`).

### 5.1 Grounding Guarantee

Neither agent may answer from the model's general knowledge.

1. A BM25 retriever (`services/protocol_retrieval_service.py`) selects protocol
   passages relevant to the event, and each passage is presented to the model
   tagged with a `chunk_id`.
2. The model must return at least one citation. This is enforced by the schema,
   not by prompt instruction — an uncited response fails validation.
3. Every returned citation is verified in Python: its `chunk_id` must be one
   that was actually retrieved, and its `quoted_text` must appear in that
   chunk. Citations failing either check are discarded and counted in
   `grounding.unverified_citation_count`.
4. If no citation survives verification, the whole result is discarded and the
   status becomes `failed` with error `ungrounded response`.

Provenance in a verified citation (`document_title`, `source_url`) is taken
from the retriever's own record, never from the model's self-report, so a real
quotation cannot be attributed to the wrong document.

### 5.2 Status Values and the No-Fabrication Rule

Both agents report a status: `success`, `failed`, or `skipped`.

| Status | Meaning |
|---|---|
| `success` | The model answered and at least one citation verified. |
| `failed` | We attempted an assessment and could not complete one. |
| `skipped` | No assessment was attempted. |

**`risk_score` and `risk_level` are `null` for every status except `success`.**
They are never `0` and never `"low"`. Absence of a detection is not evidence of
low risk, and a provider outage is not evidence of safety. Consumers must render
this state distinctly rather than defaulting it.

Skip reasons (`metadata.reason`):

| Reason | Cause |
|---|---|
| `no_event` | `detected` was `false` — the scan ran and found nothing. |
| `detection_unavailable` | `detected` was `null` — the scan could not run. |
| `unsupported_event` | The event was not a fire event. |
| `analysis_not_requested` | The caller passed `include_analysis=false`. |
| `risk_analysis_unavailable` | Planning only. Risk analysis did not succeed. |

Failure categories (`error`) come from a closed vocabulary: `authentication
error`, `rate limited`, `invalid request`, `HTTP error`, `timeout`, `network
error`, `malformed response`, `missing credentials`, `provider error`, plus
`no protocol match`, `protocol corpus unavailable`, and `ungrounded response`.

### 5.2a Two Different Meanings of "Risk" — Read This First

The system contains **two** components that emit `risk_score` and `risk_level`,
and they are not interchangeable:

| | `FireRiskPredictionAgent` | `RiskAnalysisAgent` |
|---|---|---|
| Question | Might a fire **start** here? | How bad is this fire that **exists**? |
| Method | ML model over weather, terrain, land cover | LLM reasoning over detected evidence + protocols |
| `risk_score` | Float **0.0-1.0** (calibrated probability) | Integer **0-100** (operational severity) |
| `risk_level` | `low` \| `medium` \| `high` | `low` \| `medium` \| `high` \| `critical` |
| `risk_semantics` | `"estimated_fire_risk"` | `"detected_event_operational_risk"` |
| Endpoint | `POST /api/fire-risk`, `GET /api/fire-risk/national-scan` | `GET /api/detected-events` |

**Every consumer must branch on `risk_semantics`, never on the score alone.**
Reading a `0.85` probability as an `85` severity — or vice versa — is a
two-order-of-magnitude error, and both fields are populated even when the score
is null so the distinction survives failure paths.

The two are complementary, not competing: prediction answers *where to watch*,
analysis answers *what to do about what is already burning*.

### 5.3 RiskAssessment Fields

* **`metadata.analysis_status`** (String): `success` | `failed` | `skipped`.
* **`metadata.model`** (String or null): Model id, null when no call was made.
* **`metadata.reason`** (String or null): Skip reason, see 5.2.
* **`event_id`** (String): Stable 12-character hash of the hotspot's position
  and acquisition time. The join key between the assessment, the plan and the
  map marker — the same fire keeps the same id across repeated scans.
* **`risk_semantics`** (String): Always `"detected_event_operational_risk"`.
  Present even when the score is null. See 5.2a.
* **`risk_score`** (Integer or null): Operational risk, 0-100.
* **`risk_level`** (String or null): `low` | `medium` | `high` | `critical`.
  **Derived in Python from `risk_score`**, never requested from the model, so
  the two cannot disagree. Bands: 0-24 low, 25-49 medium, 50-79 high, 80-100
  critical.
* **`confidence`** (String or null): `low` | `medium` | `high`. How well the
  evidence supports the score.
* **`primary_drivers`** (Array of Strings): The signals that drove the score.
* **`explanation`** (String or null): Plain-language justification.
* **`evidence_gaps`** (Array of Strings): What could not be determined,
  typically because an enrichment source failed.
* **`grounding`** (Object): See 5.5.
* **`error`** (String or null): Failure category, see 5.2.

Note this object deliberately carries **no** `recommended_units` and no
`response_plan`. Those belong to the response plan.

### 5.4 ResponsePlan Fields

The plan is designed to be **self-contained**, so that a downstream resource
allocation agent receiving only the plan can act on it. The identity block below
is what makes that true; correlating a plan to an event by "they arrived in the
same HTTP response" is not a contract.

* **`metadata.planning_status`** (String): `success` | `failed` | `skipped`.
* **`event_id`** (String or null): Same id as the corresponding assessment.
  Null only when the plan was built with no event context at all.
* **`event_type`** (String): `"fire"`.
* **`location`** (Object): The event's coordinates.
* **`responding_to`** (Object): The assessment this plan answers —
  `risk_score`, `risk_level` and `risk_semantics`, all null on non-success
  paths. Carries the semantics so a consumer knows which scale the score is on.
* **`recommended_units`** (Array of Strings): From a closed vocabulary —
  `fire_department`, `police`, `medical_services`, `municipal_emergency_team`,
  `home_front_command`, `aerial_firefighting`, `forestry_service`,
  `utility_operator`.
* **`response_actions`** (Array of Objects): Ordered by priority; list position
  is the order. Each has `action` (String), `responsible_unit` (one of the
  above), and `timeframe` (`immediate` | `within_1_hour` | `within_6_hours` |
  `ongoing`). Every `responsible_unit` must also appear in
  `recommended_units`; a plan violating this is rejected.
* **`plan_summary`** (String or null): One-paragraph overview.
* **`assumptions`** (Array of Strings): What the plan takes for granted.
* **`grounding`** (Object): See 5.5.
* **`error`** (String or null): Failure category, see 5.2.

Planning is gated on risk analysis: if `analysis_status` is not `success`, no
model call is made and the plan is `skipped`. Planning a response to a risk that
could not be determined would hand an operator actions justified by nothing.

### 5.5 Grounding Object

Attached to both the assessment and the plan.

* **`retriever`** (String): Retrieval method, currently `bm25`.
* **`retrieved_chunk_ids`** (Array of Strings): Everything retrieved, including
  passages the model chose not to cite.
* **`citations`** (Array of Objects): Verified citations only. Each carries
  `chunk_id`, `document_id`, `document_title`, `source_url`, `heading_path`,
  `quoted_text`, `supports`, and `verified` (always `true`).
* **`unverified_citation_count`** (Integer): How many citations were discarded.
  A non-zero value on a successful result means the model cited loosely but at
  least one citation held.

### 5.6 GET /api/detected-events

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `latitude` | Float | 31.783333 | 29.45-33.35 | Within Israel's borders. |
| `longitude` | Float | 35.216667 | 34.26-35.90 | Within Israel's borders. |
| `radius_km` | Float | 5.0 | 1-50 | Hotspot relevance radius. |
| `day_range` | Integer | 2 | 1-10 | Recent days of satellite data. |
| `include_analysis` | Boolean | true | — | False skips both model calls. |

Responses:

* **`200 OK`** — Always returned when the pipeline ran, including when nothing
  was detected (`events: []`) and when satellite detection failed
  (`events: []`, `collection_status: "failed"`). This differs from
  `/api/environmental-data`, which returns 502 on provider failure. The
  difference is intentional: this endpoint is fetched on dashboard load with no
  user-visible error path, so a 5xx would silently blank the map.
* **`422 Unprocessable Entity`** — A parameter outside the ranges above.
* **`500 Internal Server Error`** — Unexpected internal error. The detail is
  masked and the exception logged server-side.

The response carries `metadata` (with a per-service status breakdown covering
`detection`, `risk_analysis`, `response_planning` and `protocols`), the `query`
that produced it, and an `events` array of zero or one event. Each event
flattens the detection, assessment and plan into one object, with
`response_plan` as flattened action strings and `response_actions` retaining
unit and timeframe. Event `id` is a stable hash of the hotspot, so repeated
scans of the same fire produce the same id.

**Performance.** The full pipeline typically takes 20-90 seconds: the
OpenStreetMap Overpass lookup alone can take 30 seconds under load, and each
model call adds several more. Pass `include_analysis=false` for a
detection-only response. A background-job endpoint would be the proper fix and
is not implemented.

---

## 6. Flood Detection Agent Contract

This section defines the current return value of
`FloodDetectionAgent.detect_floods()`.

The detector reads cached Water Authority observations from PostgreSQL. It does
not call the provider or schedule collection itself. One invocation evaluates
all hydrometric stations, so its result is a national scan containing zero or
more detected events, watches and coverage gaps.

The evaluation timestamp is also the query's `as_of` boundary. Hydrometric and
rainfall observations later than that timestamp are excluded from both the
latest reading and the history windows, so a replay cannot accidentally use
data that arrived afterward.

`flow_intensity` is hydrological flow intensity. It is not inundation depth,
damage severity, population exposure or final operational risk. Those belong
to downstream emergency analysis.

### 6.1 Root FloodDetectionResult

| Field | Type | Meaning |
|---|---|---|
| `metadata.timestamp` | ISO 8601 String | UTC time at which the cached observations were assessed. |
| `metadata.collection_status` | String | `success` when station histories were read; `failed` when the primary database read failed. A degraded collector does not change this field to `failed` when usable cache remains. |
| `metadata.history_window_minutes` | Integer | Observation-history window used for trends. Currently `90`. Present only after a successful primary database read. |
| `event_type` | String | Always `flood`. |
| `detected` | Boolean or null | Overall result; see the rules below. |
| `detected_events` | Array of FloodEvent | Confirmed or likely hydrological signals. Every member has `detected: true`. |
| `watch_events` | Array of FloodEvent | Signals awaiting persistence. Every member has `detected: false` and `detection_state: flood_watch`. |
| `input_station_count` | Integer | Number of station records returned by the repository: all active catalogued hydrometric stations, plus uncatalogued or inactive stations with a recent observation. Active stations without observations are included and reported as unassessed. |
| `assessed_station_count` | Integer | Number classified as detected, watch or clear. Clear stations are counted but are not returned as event objects. |
| `unassessed_stations` | Array of Objects | Stations that could not be classified safely; see 6.9. |
| `source_status` | Object | Database, collector/cache and stream-network health; see 6.2. |
| `source_errors` | Object, optional | Technical failures of optional enrichments, currently `collector_runs` and/or `stream_network`. Detection may still succeed. |
| `error` | String, optional | Primary database failure. Present only when `metadata.collection_status` is `failed`. |

The root `detected` value follows these rules:

* `true` — at least one member exists in `detected_events`. Coverage gaps may
  still exist and remain visible in `unassessed_stations`.
* `false` — no detected event exists and every input station was assessable.
  `watch_events` may still be non-empty.
* `null` — no event was detected, but there were no input histories or at least
  one station could not be assessed. It is never converted to `false`.

### 6.2 Source and Cache Status

`source_status.hydrology_database` is `success` or `failed`.
`source_status.stream_network` is `success`, `failed` or `not_required`.
The stream network is required only when at least one returned event has a
reliably matched stream.

`source_status.hydrometric_observations` and
`source_status.rainfall_observations` have the following shape:

| Field | Type | Meaning |
|---|---|---|
| `status` | String | Effective source/cache status described below. |
| `collector_source` | String | Source key recorded in `collector_runs`. |
| `latest_collection_status` | String or null | Raw latest run status, normally `ok`, `failed` or `running`; null when no run exists or run history is unavailable. |
| `latest_started_at` | ISO 8601 String or null | Start of the latest recorded run. |
| `latest_finished_at` | ISO 8601 String or null | End of the latest recorded run. |
| `latest_rows_written` | Integer or null | Rows reported written by that invocation. Zero can be a successful idempotent refresh. |
| `latest_run_has_error` | Boolean | Whether the latest run stored an error. The provider error text is not copied into this object. |
| `cached_data_available` | Boolean | At least one valid cached observation timestamp is available. |
| `cached_data_fresh` | Boolean | At least one cached station has a reading within its freshness limit. |
| `cache_coverage` | String | `fresh`, `partial`, `stale` or `unavailable`. |
| `cached_station_count` | Integer | Unique cached stations visible to this scan. |
| `fresh_station_count` | Integer | Cached stations within the freshness limit. |
| `latest_observed_at` | ISO 8601 String or null | Newest visible cached observation. |

Effective `status` values:

| Value | Meaning |
|---|---|
| `success` | Latest collection is healthy and all visible cached stations are fresh, or a collection is currently running while the existing cache is fully fresh. |
| `degraded` | Fresh cache can still be used, but the latest run failed, the cache has only partial fresh coverage, or the raw run state is unexpected. |
| `failed` | The latest collection failed and no fresh cache remains. |
| `stale` | The latest collection reported `ok`, but all visible cache is older than the freshness limit. |
| `collecting` | A collection is running and there is no fresh cache yet. |
| `never_run` | No matching row exists in `collector_runs`. |
| `unavailable` | The latest run reported `ok`, but no usable cached observation is visible. |
| `unknown` | Collector-run history could not be read, or an unknown run state exists without fresh cache. |

Hydrometric and rainfall cache freshness are currently 30 minutes. Rain cache
health is derived from unique rain stations visible through the hydrometric
stations' drainage basins; it is not a count of every rain station in Israel.

### 6.3 FloodEvent Core Fields

| Field | Type | Meaning |
|---|---|---|
| `event_key` | String | Stable station-based identity: `flood:water_authority:<source_station_id>`. Multiple affected stations currently produce separate event objects. |
| `metadata.timestamp` | ISO 8601 String | Time of detector evaluation. |
| `metadata.collection_status` | String | `success` for a returned event. |
| `event_type` | String | Always `flood`. |
| `detected` | Boolean | `true` in `detected_events`; `false` in `watch_events`. |
| `detection_state` | String | `observed_high_flow`, `flood_wave_likely`, `rapid_flow_detected` or `flood_watch`. |
| `flow_intensity` | String | `negligible`, `low`, `medium`, `high`, `very_high`, `extreme` or `unranked`. This is not operational severity. |
| `confidence` | String | Detection confidence: `low`, `medium` or `high`. This is separate from stream-match and route confidence. |
| `reasons` | Array of Strings | Machine-readable evidence supporting the state. |
| `observed_at` | ISO 8601 String | Timestamp of the station's newest observation used for the event. |
| `location` | Object | `known`, `latitude` and `longitude`. Coordinates are the hydrometric station, not a flood boundary. |
| `station` | Object | `source_station_id`, internal `hydrometric_station_id`, `name_he` and `name_en`. |
| `drainage_basin` | Object | `basin_id`, `name_he` and `name_en`; values may be null when the station cannot be spatially assigned. |
| `hydrological_evidence` | Object | Current measurement, threshold and trend evidence; see 6.5. |
| `rainfall_context` | Object | Basin-level rain summary; see 6.6. |
| `rainfall_evidence` | Array of Objects | Per-gauge values supporting the rain summary. |
| `stream_context` | Object | Conservative station-to-stream match; see 6.7. |
| `downstream_route` | Object | Approximate declared stream sequence; see 6.8. |

Detection states have the following semantics:

| State | Meaning |
|---|---|
| `observed_high_flow` | Discharge is at or above Q5, or a persistent Q2 crossing is accompanied by a rapid persistent rise. |
| `flood_wave_likely` | A Q2 crossing persisted, or active rapidly rising flow exists at a station without a usable Q2 threshold. |
| `rapid_flow_detected` | Active flow is rising rapidly and persistently below Q2 at a station with a usable Q2 threshold. The surrounding threshold set may be complete or partial. |
| `flood_watch` | One Q2 crossing exists but has not yet met the persistence requirement. |

`flow_intensity` is derived from usable return-period discharge thresholds:

| Intensity | Current mapping |
|---|---|
| `extreme` | An available Q50 threshold is crossed. A Q100 crossing remains visible in `crossed_thresholds` but has no separate intensity label. |
| `very_high` | An available Q20 threshold is crossed and no available higher intensity threshold is crossed. |
| `high` | An available Q10 threshold is crossed and no available higher intensity threshold is crossed. |
| `medium` | An available Q5 threshold is crossed and no available higher intensity threshold is crossed. |
| `low` | An available Q2 threshold is crossed and no available higher intensity threshold is crossed, or active flow exists without a crossed available threshold. |
| `negligible` | Water level is below the station's flow-start level. Equality means flow has started and is not negligible. |
| `unranked` | Current discharge or usable discharge thresholds are unavailable, so intensity cannot be ranked honestly. |

When `threshold_status` is `partial`, the intensity is the highest band that can
be confirmed from the available thresholds. It is a conservative lower bound:
a missing threshold above or between supplied thresholds may prevent the
detector from proving a higher band.

### 6.4 Detection Confidence

Detection confidence does not estimate flood probability. It describes how
strongly the available evidence supports the reported state.

* A `flood_watch` always has `low` confidence.
* Usable complete or partial thresholds, a persistent crossing and a known
  location produce `high` confidence.
* A rapid rise corroborated by recent rain in the same basin and a known
  location produces `high` confidence.
* A rapid rise with a known location but without fresh rain support produces
  `medium` confidence.
* Other classified events with usable complete or partial thresholds produce
  `medium`; otherwise confidence is `low`.

Rainfall can support confidence but does not independently turn a clear
hydrometric station into a detected flood event.

### 6.5 Hydrological Evidence

`hydrological_evidence` contains:

* `discharge_m3s` and `water_height_m` — newest measured values, nullable
  independently.
* `flow_start_water_level_m` — station-specific flow-start level, or null.
* `flow_started` — Boolean when both water height and flow-start level are
  available; otherwise null.
* `threshold_status` — `valid`, `partial`, `unavailable`, `non_positive` or
  `non_monotonic`. `valid` means all six Q2, Q5, Q10, Q20, Q50 and Q100 values
  are positive and non-decreasing. `partial` means any subset is missing while
  the supplied values remain positive and non-decreasing in return-period
  order. Missing Q2 or a gap in the middle does not invalidate the other
  supplied thresholds. `unavailable` means all are missing. Non-positive and
  non-monotonic series are not used.
* `available_return_periods` and `missing_return_periods` — ordered lists that
  describe which of Q2, Q5, Q10, Q20, Q50 and Q100 were supplied. Supplied
  periods are usable only when `threshold_status` is `valid` or `partial`.
* `crossed_thresholds` — array of `{return_period_years, threshold_m3s}` for
  every usable supplied threshold crossed by current discharge.
* `highest_crossed_return_period_years` — greatest crossed return period, or
  null.
* `q2_persistence_observations` — number of consecutive newest observations at
  or above Q2.
* `rapid_stage_rise` and `rapid_discharge_rise` — Boolean policy triggers.
* `trend` — observation count, consecutive-rise counts, latest rise rates and
  `changes` for `10m`, `30m` and `60m`. Each window is null when no suitable
  earlier observation exists; otherwise it contains `elapsed_minutes`,
  `start_observed_at`, `water_height_change_m` and
  `discharge_change_m3s`.

Current provisional rapid-rise policy values are two consecutive rises,
`0.25 m/hour` for stage, or `0.25 × Q2/hour` for discharge. They are operational
heuristics, not Water Authority flood thresholds.

### 6.6 Rainfall Context and Evidence

`rainfall_context` describes rain gauges assigned to the same drainage basin as
the hydrometric station:

* `association` — `same_drainage_basin` or `unavailable`.
* `basin_id`, `station_count`, `stations_with_observations`,
  `fresh_station_count`, `latest_observation_at`, `is_fresh` and
  `recent_rain_detected`.
* `maximum_10m_mm`, `mean_10m_mm`, `maximum_1h_mm`, `mean_1h_mm`,
  `maximum_6h_mm`, `mean_6h_mm`, `maximum_24h_mm` and `mean_24h_mm`.
  Only fresh gauges contribute; values are null when none are fresh.
* `limitations` currently contains
  `same_basin_does_not_prove_upstream_subcatchment` and
  `rainfall_has_not_yet_been_compared_with_local_idf`.

Values from different gauges are never summed, because that would count the
same storm multiple times. The summary reports maxima and arithmetic means.

Every `rainfall_evidence` member contains `source_station_id`, `name_he`,
`name_en`, `latitude`, `longitude`, `latest_observed_at`, `rainfall_10m_mm`,
`rainfall_1h_mm`, `rainfall_6h_mm` and `rainfall_24h_mm`. Missing measurements
remain null and are never fabricated as zero.

### 6.7 Stream Context

The stream match is an enrichment and never changes the hydrological detection
state or detection confidence. Candidate streams are first restricted to the
station's drainage basin and a 2 km search radius.

`stream_context` contains:

* `association` — `same_drainage_basin` or `unavailable`.
* `matched` — whether a stream is reliable enough to use for routing.
* `confidence` — `high`, `medium`, `low` or `unavailable`.
* `method` — `same_basin_name_and_distance`,
  `same_basin_distance_only` or null.
* `candidate_count` and `distinct_candidate_count`.
* `stream` — selected stream when `matched` is true; otherwise null.
* `nearest_candidate` — diagnostic candidate for an unresolved match;
  otherwise null.
* `warnings` — machine-readable limitations or ambiguity reasons.

A stream object contains `stream_id`, `object_id`, `name_he`,
`water_source_id`, `main_catchment_code`, `main_catchment_name`,
`draining_water_id`, `draining_water_name`, `distance_m` and
`name_matches_station`.

The default policy treats a name match within 100 m as high confidence. A name
match within 1 km, or a unique stream within 100 m without a matching name, is
medium confidence. Distance-only matches beyond 100 m, candidates beyond 1 km
and similarly close distinct streams remain unresolved.

### 6.8 Downstream Route

`downstream_route` follows Water Authority `draining_water_id` relationships
from a reliably matched origin stream. Coordinate order in a line geometry is
never interpreted as flow direction.

| Field | Type | Meaning |
|---|---|---|
| `status` | String | `complete`, `partial` or `unavailable`. Complete means only that a declared network end was reached; it does not prove a physical outlet. |
| `confidence` | String | Initially inherits stream-match confidence and becomes `low` for a cycle or conflicting downstream connections. |
| `method` | String | Always `water_authority_draining_water_id`. |
| `origin_water_source_id` | Integer or null | Provider water-source id of the selected origin stream. |
| `segment_count` | Integer | Number of returned stream-network nodes. |
| `segments` | Array of Objects | Ordered nodes from the origin downstream. |
| `termination` | String | Why traversal stopped. |
| `limitations` | Array of Strings | Fixed statements preventing hydraulic over-interpretation. |

Each segment contains `hop`, `name_he`, `water_source_id`, `object_ids`,
`feature_count`, `main_catchment_code`, `main_catchment_name`,
`draining_water_id`, `draining_water_name`, `representative_location` and
`topology_conflict`. Hop zero additionally contains `matched_object_id`.
Representative locations are map reference points, not flood boundaries.

Current termination values are:

* `declared_network_end`
* `maximum_hops_reached`
* `origin_stream_unmatched`
* `origin_water_source_id_unavailable`
* `stream_network_unavailable`
* `stream_network_empty`
* `origin_stream_missing_from_network`
* `downstream_stream_missing_from_network`
* `cycle_detected`
* `conflicting_downstream_connections`

The traversal limit is currently 20 downstream hops.

### 6.9 Unassessed Stations

Each `unassessed_stations` member contains `source_station_id`,
`hydrometric_station_id`, `observed_at`, `discharge_m3s`, `water_height_m`,
`location_known`, `reason` and optional diagnostic details. The detector's
internal `unassessed` classification is not emitted as a separate `status`
field in the public result.

Current reason values are `hydrometric_observation_unavailable`,
`invalid_observation_timestamp`, `stale_observation`,
`hydrological_measurements_unavailable` and
`active_flow_without_usable_q2_threshold_or_trend`. The final reason
also includes `threshold_status`, `available_return_periods`,
`missing_return_periods` and `observation_count`.

### 6.10 Example Successful Scan

The example is a detector-level result, not the response of an HTTP endpoint:

```json
{
  "metadata": {
    "timestamp": "2026-09-14T10:00:00+00:00",
    "collection_status": "success",
    "history_window_minutes": 90
  },
  "event_type": "flood",
  "detected": true,
  "detected_events": [
    {
      "event_key": "flood:water_authority:49",
      "metadata": {
        "timestamp": "2026-09-14T10:00:00+00:00",
        "collection_status": "success"
      },
      "event_type": "flood",
      "detected": true,
      "detection_state": "observed_high_flow",
      "flow_intensity": "high",
      "confidence": "high",
      "reasons": [
        "discharge_at_or_above_5_year_threshold",
        "discharge_threshold_crossing_persisted",
        "rapid_persistent_hydrological_rise"
      ],
      "observed_at": "2026-09-14T09:50:00+00:00",
      "location": {
        "known": true,
        "latitude": 31.5,
        "longitude": 34.8
      },
      "station": {
        "source_station_id": 49,
        "hydrometric_station_id": 7,
        "name_he": null,
        "name_en": "Example station"
      },
      "drainage_basin": {
        "basin_id": 12,
        "name_he": null,
        "name_en": "Example basin"
      },
      "stream_context": {
        "association": "same_drainage_basin",
        "matched": true,
        "confidence": "high",
        "method": "same_basin_name_and_distance",
        "candidate_count": 1,
        "distinct_candidate_count": 1,
        "stream": {
          "stream_id": 21,
          "object_id": 301,
          "name_he": "Example Stream",
          "water_source_id": 9001,
          "main_catchment_code": "12",
          "main_catchment_name": "Example basin",
          "draining_water_id": null,
          "draining_water_name": null,
          "distance_m": 18.4,
          "name_matches_station": true
        },
        "nearest_candidate": null,
        "warnings": []
      },
      "hydrological_evidence": {
        "discharge_m3s": 50.0,
        "water_height_m": 1.58,
        "flow_start_water_level_m": 1.2,
        "flow_started": true,
        "threshold_status": "valid",
        "available_return_periods": [2, 5, 10, 20, 50, 100],
        "missing_return_periods": [],
        "crossed_thresholds": [
          {"return_period_years": 2, "threshold_m3s": 17.0},
          {"return_period_years": 5, "threshold_m3s": 37.0},
          {"return_period_years": 10, "threshold_m3s": 48.0}
        ],
        "highest_crossed_return_period_years": 10,
        "q2_persistence_observations": 3,
        "rapid_stage_rise": true,
        "rapid_discharge_rise": true,
        "trend": {
          "observation_count": 3,
          "consecutive_stage_rises": 2,
          "consecutive_discharge_rises": 2,
          "recent_stage_rise_m_per_hour": 0.84,
          "recent_discharge_rise_m3s_per_hour": 60.0,
          "recent_discharge_rise_q2_per_hour": 3.53,
          "changes": {
            "10m": {
              "elapsed_minutes": 10.0,
              "start_observed_at": "2026-09-14T09:40:00+00:00",
              "water_height_change_m": 0.16,
              "discharge_change_m3s": 12.0
            },
            "30m": {
              "elapsed_minutes": 20.0,
              "start_observed_at": "2026-09-14T09:30:00+00:00",
              "water_height_change_m": 0.28,
              "discharge_change_m3s": 20.0
            },
            "60m": null
          }
        }
      },
      "rainfall_context": {
        "association": "same_drainage_basin",
        "basin_id": 12,
        "station_count": 0,
        "stations_with_observations": 0,
        "fresh_station_count": 0,
        "latest_observation_at": null,
        "is_fresh": false,
        "recent_rain_detected": false,
        "limitations": [
          "same_basin_does_not_prove_upstream_subcatchment",
          "rainfall_has_not_yet_been_compared_with_local_idf"
        ],
        "maximum_10m_mm": null,
        "mean_10m_mm": null,
        "maximum_1h_mm": null,
        "mean_1h_mm": null,
        "maximum_6h_mm": null,
        "mean_6h_mm": null,
        "maximum_24h_mm": null,
        "mean_24h_mm": null
      },
      "rainfall_evidence": [],
      "downstream_route": {
        "status": "complete",
        "confidence": "high",
        "method": "water_authority_draining_water_id",
        "origin_water_source_id": 9001,
        "segment_count": 1,
        "segments": [
          {
            "hop": 0,
            "name_he": "Example Stream",
            "water_source_id": 9001,
            "object_ids": [301],
            "feature_count": 1,
            "main_catchment_code": "12",
            "main_catchment_name": "Example basin",
            "draining_water_id": null,
            "draining_water_name": null,
            "representative_location": {
              "latitude": 31.49,
              "longitude": 34.81
            },
            "topology_conflict": false,
            "matched_object_id": 301
          }
        ],
        "termination": "declared_network_end",
        "limitations": [
          "route_uses_declared_connections_not_hydraulic_simulation",
          "coordinate_order_is_not_used_as_flow_direction",
          "route_does_not_predict_inundation_extent_or_travel_time",
          "representative_points_are_not_flood_boundaries"
        ]
      }
    }
  ],
  "watch_events": [],
  "input_station_count": 1,
  "assessed_station_count": 1,
  "unassessed_stations": [],
  "source_status": {
    "hydrology_database": "success",
    "hydrometric_observations": {
      "status": "success",
      "collector_source": "water_authority_hydrometric_observations",
      "latest_collection_status": "ok",
      "latest_started_at": "2026-09-14T09:54:00+00:00",
      "latest_finished_at": "2026-09-14T09:55:00+00:00",
      "latest_rows_written": 12,
      "latest_run_has_error": false,
      "cached_data_available": true,
      "cached_data_fresh": true,
      "cache_coverage": "fresh",
      "cached_station_count": 1,
      "fresh_station_count": 1,
      "latest_observed_at": "2026-09-14T09:50:00+00:00"
    },
    "rainfall_observations": {
      "status": "unavailable",
      "collector_source": "water_authority_rainfall_observations",
      "latest_collection_status": "ok",
      "latest_started_at": "2026-09-14T09:54:00+00:00",
      "latest_finished_at": "2026-09-14T09:55:00+00:00",
      "latest_rows_written": 0,
      "latest_run_has_error": false,
      "cached_data_available": false,
      "cached_data_fresh": false,
      "cache_coverage": "unavailable",
      "cached_station_count": 0,
      "fresh_station_count": 0,
      "latest_observed_at": null
    },
    "stream_network": "success"
  }
}
```

### 6.11 Primary Database Failure

When station histories cannot be read, the detector returns an inconclusive
result rather than claiming that no flood exists:

```json
{
  "metadata": {
    "timestamp": "2026-09-14T10:00:00+00:00",
    "collection_status": "failed"
  },
  "event_type": "flood",
  "detected": null,
  "detected_events": [],
  "watch_events": [],
  "input_station_count": 0,
  "assessed_station_count": 0,
  "unassessed_stations": [],
  "source_status": {
    "hydrology_database": "failed"
  },
  "error": "RuntimeError: database unavailable"
}
```
