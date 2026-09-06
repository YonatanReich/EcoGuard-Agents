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
Fetches, normalizes, and unifies real-time weather forecasts and regional geospatial context around a specific coordinate. The endpoint communicates internally with the `WeatherDataAgent` and `GeospatialContextAgent`, validating inputs strictly within Israel's boundaries to prevent resource exhaustion and unauthorized out-of-bounds scanning.

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