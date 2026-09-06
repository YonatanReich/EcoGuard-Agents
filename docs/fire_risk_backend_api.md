# Fire Risk backend API

EcoGuard's production fire-risk path is **Current Risk only**. It estimates how
closely current environmental conditions resemble historically higher-risk fire
conditions. It does not indicate that a fire has been detected and remains
separate from FIRMS or Telegram event evidence.

Historical forecast deterioration was evaluated separately and showed no
predictive benefit in the completed pilot. Forecast and Combined Risk are not
production runtime services or API response fields.

## Point Current Risk

`POST /api/fire-risk`

Request:

```json
{
  "latitude": 31.9,
  "longitude": 34.9
}
```

The backend resolves persisted grid/static features, reads strictly
pre-evaluation weather history from the rolling local weather cache, builds the
existing 44-feature payload, and passes it to `FireRiskPredictionAgent`. It does
not make a fresh multi-day weather request during prediction. A complete
44-feature payload may instead be supplied explicitly in `current_features`.

Successful response:

```json
{
  "status": "available",
  "location": {
    "latitude": 31.9,
    "longitude": 34.9
  },
  "current_risk": {
    "status": "available",
    "score": 0.576,
    "level": "high",
    "semantics": "estimated_fire_risk",
    "main_factors": [],
    "reason": null,
    "missing_runtime_inputs": [],
    "model_version": "..."
  },
  "actual_fire_detection": {
    "included": false,
    "semantics": "separate_firms_or_telegram_evidence"
  }
}
```

If required cached history or another runtime input is unavailable, the endpoint
returns a structured `unavailable` result. It never substitutes zero or fabricated
feature values. Model or schema failures return a structured `error` result.

## National Current Risk scan

`GET /api/fire-risk/national-scan`

The response contains:

- `evaluation_time`
- evaluated risk records in `cells`
- explicit `unavailable_cells`
- summary counts and highest-risk cells
- `semantics: "estimated_fire_risk_not_actual_fire_detection"`
- refresh metadata

Without an explicit evaluation time, the endpoint reuses the latest persisted
national-scan snapshot when available. If no snapshot exists, it performs an
offline scan from the existing local grid, static features, FIRMS history, and
weather cache, then persists the result. An explicitly supplied evaluation time
requests a deterministic scan for that time.

Cells outside the configured EcoGuard operational service area are not evaluated.
Cells inside it that lack required data remain explicitly unavailable and receive
no default risk score.

## Periodic refresh

The in-process refresh orchestrator runs at a configurable conservative cadence:

1. incrementally refresh the rolling weather cache;
2. run the national Current Risk scan when the cache result is usable;
3. atomically persist the newest scan snapshot;
4. expose refresh status and timestamps through `refresh_metadata`.

The orchestrator prevents overlapping runs and preserves cached data across
partial provider failures. This flow does not acquire forecast-deterioration data
and does not alter the trained model, calibration, thresholds, or risk semantics.
