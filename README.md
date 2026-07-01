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