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
