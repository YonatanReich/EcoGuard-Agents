# Flood collection

Everything the flood lane watches: how much water is in the streams and the
fixed map of where that water goes.

| File | What it provides |
|---|---|
| `hydrometric_observations.py` | Stream gauge readings |
| `hydrometric_stations.py` | The gauges themselves, and their official flood thresholds |
| `rainfall_idf.py` | How much rain counts as unusual, by duration |
| `hydrology_static.py` | Drainage basins, streams and road markers |
| `road_network.py` | Road geometry, for saying which roads a flood affects |
| `static_context.py`, `signal_rows.py` | The stored shapes the detector reads |

## Thresholds matter here

A gauge without official flood thresholds or a reviewed operational flow
regime cannot say which detector rule applies, so its readings are not stored
or evaluated at all. Only active gauges with both are eligible. Being in the
catalogue is not the same as being usable.

The reviewed classification is maintained in
`data/reference/Floods/hydrometric_station_flow_regimes.csv`. The static
hydrology loader validates that every listed gauge is active and has complete
thresholds, then replaces the database classifications atomically. Active
complete gauges omitted from the file remain unclassified and produce a
warning.
