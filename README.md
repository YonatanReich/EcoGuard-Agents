# EcoGuard Agents

EcoGuard Agents is a multi-agent system for real-time environmental crisis management in Israel.

The system will collect environmental data, detect crisis events, analyze risk levels, recommend relevant authorities to activate, and generate response plans.

## Project Structure

- backend: FastAPI server and internal APIs
- frontend: React web dashboard and map interface
- agents: Autonomous agents and risk analysis logic
- tests: Automated tests
- docs: Project documentation, sprint summaries and architecture files
## Backend

The backend is built with FastAPI.

### Setup

Create and activate a virtual environment:

```bash
python -m venv venv
.\venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### Configure API keys

Copy `.env.example` to `.env` at the repository root and fill it in. `.env` is
gitignored; never commit real keys.

```bash
cp .env.example .env
```

| Variable | Needed for | Without it |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Risk analysis and response planning | Events are detected but not assessed; status reports `missing credentials` |
| `NASA_FIRMS_API_KEY` | Satellite fire detection | `/api/detected-events` cannot detect anything |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | Telegram fire intelligence listener | That standalone script cannot run |

The frontend map additionally needs `VITE_MAPTILER_KEY` in
`frontend/.env.local` — see the frontend section below.

Every agent degrades rather than crashing when a key is absent, so the app still
runs with none of them set. It just reports honestly about what it could not do.

### Run the tests

```bash
pytest
```

The whole suite runs offline — no API keys, no network. To verify the Claude
integration end to end (a real call, structured output, citation verification,
and prompt caching), run the smoke check, which needs `ANTHROPIC_API_KEY`:

```bash
python scripts/claude_smoke_check.py
```

### Run backend locally

```bash
uvicorn backend.main:app --reload
```

### Run frontend locally
```bash
cd frontend
npm run dev
```

The API will be available at:

```text
http://127.0.0.1:8000/
```

Expected response:

```json
{
  "message": "EcoGuard Agents API is running",
  "status": "success"
}
```

## API Endpoints

### 1. Get Unified Environmental Data
`GET /api/environmental-data`

#### Description
Unifies stored weather observations with live regional geospatial context around a specific coordinate. Inputs are validated strictly within Israel's boundaries.

The two halves no longer work the same way. `WeatherDataAgent` **reads the collection layer's store** rather than calling Open-Meteo — the coordinate is answered by the 5 km grid cell containing it, and `metadata.services.weather.observation` names that cell, its distance in metres, and when the reading was taken. `GeospatialContextAgent` still calls OpenStreetMap Overpass live, because nothing collects that on a timer, and it is what makes this endpoint slow.

Two consequences worth knowing:

* `weather.forecast.daily` is **empty**. The store holds observations, and a forecast is not one.
* A coordinate with no cell within 5 km carrying a reading under 6 hours old returns `collection_status: "failed"` for the weather half, rather than reaching out to fetch one.

See [`docs/weather_collection.md`](docs/weather_collection.md) for the collection layer.

#### Query Parameters

| Parameter | Type | Required | Default | Validation / Restrictions | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `latitude` | Float | No | `31.783333` (Jerusalem) | Must be between `29.45` and `33.35` | Geographical latitude within Israel's borders (South to North). |
| `longitude` | Float | No | `35.216667` (Jerusalem) | Must be between `34.26` and `35.90` | Geographical longitude within Israel's borders (West to East). |

#### HTTP Response Status Codes

* **`200 OK`**
  The request was successful. A unified JSON object containing metadata, services health status, core weather tracking, and geospatial elements is returned.
  
* **`422 Unprocessable Entity`**
  Input validation failed. This happens automatically if the coordinates are missing, malformed, or fall completely outside Israel's bounding box.
  
* **`502 Bad Gateway`**
  Service failure. Triggered when both external downstream environmental providers (Open-Meteo and OpenStreetMap Overpass API) fail or time out simultaneously.
  
* **`500 Internal Server Error`**
  An unexpected server-side error occurred. For security and to prevent information disclosure vulnerabilities, the detailed stack trace is masked from the client and securely logged on the backend console.

---

### 2. Detect, Assess and Plan for Fire Events
`GET /api/detected-events`

#### Description
Runs the full crisis pipeline for one coordinate: `FireDetectionAgent` looks for
NASA FIRMS satellite hotspots and enriches them with GWIS/EFFIS fire weather,
Open-Meteo conditions and OpenStreetMap context; `RiskAnalysisAgent` scores the
operational risk; `ResponsePlanningAgent` produces the units to activate and the
actions to take.

Both reasoning agents call Claude and are **grounded in retrieved protocol
text** rather than the model's general knowledge. Passages are retrieved from
the committed corpus in [`data/protocols/`](data/protocols/) by BM25, the schema
requires at least one citation, and every citation is verified in Python against
the passage it claims to quote. A result whose citations do not verify is
discarded rather than served.

#### Query Parameters

| Parameter | Type | Required | Default | Validation / Restrictions | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `latitude` | Float | No | `31.783333` (Jerusalem) | Between `29.45` and `33.35` | Latitude within Israel's borders. |
| `longitude` | Float | No | `35.216667` (Jerusalem) | Between `34.26` and `35.90` | Longitude within Israel's borders. |
| `radius_km` | Float | No | `5.0` | Between `1` and `50` | How far from the point a hotspot counts as relevant. |
| `day_range` | Integer | No | `2` | Between `1` and `10` | How many recent days of satellite data to inspect. |
| `include_analysis` | Boolean | No | `true` | — | Set `false` to skip both model calls for a fast, detection-only response. |

#### HTTP Response Status Codes

* **`200 OK`**
  The pipeline ran. This includes the cases where nothing was detected
  (`events: []`) and where satellite detection failed (`events: []` with
  `collection_status: "failed"`). Unlike `/api/environmental-data`, provider
  failure is reported in the body rather than as a 502 — the dashboard fetches
  this on page load and has no user-visible error path, so a 5xx would blank the
  map with no explanation.

* **`422 Unprocessable Entity`**
  A parameter fell outside the ranges above.

* **`500 Internal Server Error`**
  An unexpected server-side error. The detail is masked and the exception logged.

#### Note on missing values

`risk_score` and `risk_level` are `null` whenever the analysis did not succeed —
never `0`, never `"low"`. Absence of a detection is not evidence of low risk, and
a provider outage is not evidence of safety. The dashboard renders that state in
grey rather than defaulting it to a colour that implies an all-clear.

#### Performance

This endpoint is slow: typically 20-90 seconds. The OpenStreetMap Overpass
lookup alone can take 30 seconds under load, and each of the two model calls adds
several more. Use `include_analysis=false` for a fast map render. A
background-job endpoint would be the proper fix and is not implemented.

The full field-by-field contract is in [`docs/api_contract.md`](docs/api_contract.md) §5.

---
### 3. Summarise a Drawn Area
`POST /api/area-summary`

#### Description
Aggregates everything in the store over a polygon the operator drew on the map —
freehand, rectangle or circle. This replaced clicking a single coordinate: a
point can only say what the temperature is *there*, while the operational
question is how many people are inside a shape and what the weather is doing
across it.

Nothing is fetched from an upstream provider, so unlike the two endpoints above
this one answers in milliseconds. Every figure is a PostGIS aggregate:

| Figure | Source | How |
| :--- | :--- | :--- |
| `population` | `population_cells` | Summed with **area weighting** — a cell half inside the polygon contributes half its people |
| `weather` | `observations` (`source='weather'`) | Mean of the newest reading per 5 km cell within half a grid step of the polygon. Wind direction is averaged as a vector, not as a number |
| `fire_danger` | `observations` (`source='fire_weather'`) | Mean FWI over the same cells, plus the single worst band inside them |
| `stations` | `fire_stations`, `police_stations`, `mda_stations` | Point-in-polygon counts |
| `area_km2` | the polygon | `ST_Area` on the spheroid |

#### Request Body

```json
{ "geometry": { "type": "Polygon", "coordinates": [[[35.0, 31.0], "..."]] } }
```

| Field | Validation |
| :--- | :--- |
| `geometry` | GeoJSON `Polygon`. Every ring closed and at least four positions; every vertex inside Israel's bounding box; at most 2,000 vertices in total |

Self-intersecting rings are accepted rather than rejected — a freehand trace
crossing its own line is the normal case, and PostGIS repairs it with
`ST_MakeValid` before measuring.

#### HTTP Response Status Codes

* **`200 OK`** — the summary. A section with no data underneath it reports
  `null` values and `cell_count: 0` rather than being omitted, so the UI can say
  "no reading here" instead of silently dropping a row.
* **`422 Unprocessable Entity`** — the geometry failed one of the checks above.
* **`503 Service Unavailable`** — the store could not be reached.

#### Loading the population grid

`population_cells` is empty until the grid is loaded, and until then
`population` reads `0`. It holds one row per raster pixel of a population
**count** grid, as the pixel's own footprint — the footprint, not the centroid,
is what makes the area weighting possible.

Download WorldPop's constrained, UN-adjusted 100 m grid for Israel
([`isr_ppp_2020_UNadj_constrained.tif`](https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/ISR/isr_ppp_2020_UNadj_constrained.tif),
1.9 MB), then:

```bash
alembic upgrade head
python -m scripts.load_population_grid data/generated/isr_ppp_2020_UNadj_constrained.tif
```

The script prints the total it loaded — 315,600 cells and 8,655,541 people for
the file above, which matches the UN's 2020 figure for Israel and is the sanity
check that the right raster went in. Pass `--coarsen 2` for 200 m cells
if the row count matters more than the resolution. It is a full reload —
`population_cells` is truncated first — because this is reference data published
once a year, not a feed.
