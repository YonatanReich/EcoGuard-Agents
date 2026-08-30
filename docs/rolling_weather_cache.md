# Rolling hourly weather cache

The standalone cache stores approximately nine days (216 hours) of UTC hourly
Open-Meteo data for the active 5 km risk grid. It is not wired into FastAPI,
Current Risk, forecast deterioration, or any scheduler yet.

`data/generated/fire_risk_weather_cache.sqlite` contains versioned metadata,
provider weather nodes, stable grid-cell mappings, raw hourly values, and update
run metrics. Cells reuse a node only when Open-Meteo returns the same provider
coordinate. The updater batches at most 50 coordinates by default.

The first run bootstraps the retained interval. Later runs detect every missing
hour, including interior gaps, fetch the smallest provider-supported date range,
and insert only the requested missing timestamps. Unique database keys make
updates idempotent. A failed batch preserves existing rows, and retention
pruning occurs only for nodes successfully refreshed.

The shared feature calculator preserves the historical model semantics:

- Lag values use the latest provider hour at or before T-1h/T-3h/T-6h/T-12h.
- All eligible timestamps are strictly earlier than evaluation time T.
- Aggregates use `[T-window, T)` for 24, 72, and 168 hours.
- Missing values remain null; no weather value is fabricated.

The live Forecast API's recent hourly values may not be identical to the Archive
API reanalysis used for model training. Provider coordinates, source kind,
units, and collection time are retained so this distribution difference can be
measured before Current Risk integration.

Run manually (this performs live batched requests):

```powershell
python -m scripts.update_fire_risk_weather_cache
```

Inspect metrics:

```sql
SELECT * FROM weather_update_runs ORDER BY started_at_utc DESC LIMIT 1;
```
