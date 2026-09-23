# Weather collection

One collector talks to Open-Meteo. Everything else reads what it wrote.

This replaced three independent paths to the same API — the scheduled
collector, a rolling SQLite cache that fed the fire-risk model, and
`WeatherDataAgent` calling the provider live on every HTTP request. Each held
its own rate-limiter state and could not see the others' traffic. Two of them
stored the same seven variables in two different places.

```
                    api.open-meteo.com
                            |
                   OpenMeteoHourlyClient          <- pacing, retries, 429 cooldown
                            |
                    WeatherCollector              <- hourly, gap-driven
                            |
                observations (source='weather')   <- Postgres, one row per cell-hour
                            |
        +-------------------+
        |                   |
  StoredWeatherFeatures  WeatherDataAgent
  (fire-risk model)      (/api/environmental-
                          data, detection)
```

Every read goes through `ecoguard/database/repositories/weather_history.py`.

## What is collected, and when

| | |
| --- | --- |
| Grid | 1,174 cells of the 5 km service area |
| Variables | `temperature_2m`, `relative_humidity_2m`, `precipitation`, `rain`, `wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m`, `weather_code` |
| Interval | 60 minutes — Open-Meteo publishes hourly, so nothing new exists sooner |
| Depth | 168 hours (7 days), which is the widest window the model's features read |
| Batch | 50 coordinates per request, 15 s apart |

The current hour is never stored. Open-Meteo serves forecast from the same
endpoint, and a forecast written as an observation is indistinguishable from
one afterwards.

## Fetching the gap, not a window

Each tick asks the database which hours it is missing and fetches exactly
those. In steady state that is one hour, so one sweep of the grid — 24
requests. When nothing is missing, **no provider call is made at all**.

This replaced a fixed six-hour lookback, which could only ever repair an outage
shorter than itself. A nine-hour rate-limit stretch on 2026-09-08 left eight
hours that nothing would ever return for; the production table held thirteen
permanently missing hours out of a sixty-seven-hour span before this change.

Gap detection is two queries, cheap one first:

1. count rows per hour — one index range scan, at most 168 rows back
2. only for hours that are *partly* stored, a per-cell lookup

An hour is written for the whole grid in one batch or not at all, so step 2
almost never runs.

Contiguous missing hours collapse into one request per cell batch: a seven-day
backfill costs the same 24 requests as a single hour, not 24 × 168.

## Bounded ticks

`MAX_REQUESTS_PER_TICK = 48` — two full sweeps of the grid. A cold start wants
seven days for every cell, and firing all of it at once is precisely how the
collector talked itself into sustained 429s before. The budget bounds a tick,
newest gaps go first, and the next tick continues. A cold start converges in a
few hours instead of tripping the rate limit in one.

48 is a multiple of 24 on purpose: it lets a range finish for *every* cell,
rather than leaving an hour stored for the first few hundred — a state the gap
query then has to resolve cell by cell.

## Hour-granular requests

The client asks for `start_hour`/`end_hour`, not `start_date`/`end_date`. The
date form is day-granular, so a six-hour window spanning midnight downloaded
two whole calendar days: 48 hourly steps per cell to keep six. At 8 variables
and 50 locations that is an eightfold overcharge against Open-Meteo's per-call
weighting, and it is what drove the collector into rate limiting in the first
place.

`tests/test_open_meteo_hourly_client.py::test_the_window_is_requested_in_hours_not_whole_days`
is the regression guard.

## Feature semantics

`ecoguard/shared/weather_features.py` is unchanged and still pure. It takes
`{"status", "hourly": {...}}` and an evaluation time and does not care where
the series came from — which is what let the model move off its private cache
without touching a single feature definition.

- Lag values use the latest hour at or before T-1h / T-3h / T-6h / T-12h.
- All eligible timestamps are strictly earlier than evaluation time T.
- Aggregates use `[T-window, T)` for 24, 72 and 168 hours.
- Missing values stay null. No weather value is ever fabricated.

`hourly_for_cells` reports `status: "success"` only when every hour of the
window is present, so a partially collected window degrades the model's own
status rather than quietly yielding features computed from a series full of
holes.

Note that the live Forecast API's recent hourly values are not identical to the
Archive API reanalysis used for model training. That distribution difference is
unmeasured.

## Point reads

`/api/environmental-data` and the FIRMS hotspot enrichment take an arbitrary
coordinate. They are answered by the nearest grid cell within 5 km whose newest
reading is under 6 hours old, and the response says which cell it used and how
far away it was:

```json
"metadata": {
  "observation": {
    "cell_id": "risk-05000m-r0046-c0015",
    "observed_at": "2026-09-10T01:00:00+00:00",
    "distance_m": 812.4
  }
}
```

No recent cell within reach returns a `collection_status: "failed"` response
rather than reaching out for one. `weather.forecast.daily` is empty — the store
holds observations, and a forecast is not one.

## Checking on it

```sql
-- Recent runs and what they wrote
SELECT source, status, started_at, finished_at, rows_written, error
FROM collector_runs WHERE source = 'weather'
ORDER BY started_at DESC LIMIT 20;

-- Holes in the series. This should return nothing.
WITH span AS (
  SELECT min(observed_at) a, max(observed_at) b
  FROM observations WHERE source = 'weather'
)
SELECT h FROM span, generate_series(a, b, interval '1 hour') h
WHERE h NOT IN (SELECT DISTINCT observed_at FROM observations WHERE source = 'weather');
```
