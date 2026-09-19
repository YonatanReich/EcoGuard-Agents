# scripts/

One-off and scheduled jobs run from the command line, not imported by the app.

Loaders that fill reference tables (`load_surface_grid`, `load_population_grid`,
`build_weather_baselines`, `build_fire_risk_grid`), the national risk scan
runner, a dev server with detection stubbed, and `claude_smoke_check` — the one
part of risk analysis that cannot be verified offline because it needs a real
model call.

Run as modules: `python -m ecoguard.scripts.load_surface_grid`

The IMS rainfall IDF loader validates the full flat export before replacing
the reconciled stations' curves atomically:

`python -m ecoguard.scripts.import_rainfall_idf path/to/idf_flat.csv`

Use `--validate-only` to check the complete source without connecting to or
changing the database.

After station coordinates or basin geometry change, rebuild the derived
same-basin links with:

`python -m ecoguard.scripts.sync_hydrometric_idf_basin_links`
