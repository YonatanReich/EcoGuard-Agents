# Flood collection

Everything the flood lane watches: how much water is in the streams, how much
rain is falling, and the fixed map of where that water goes.

| File | What it provides |
|---|---|
| `hydrometric_observations.py` | Stream gauge readings |
| `hydrometric_stations.py` | The gauges themselves, and their official flood thresholds |
| `rainfall_observations.py` | Rain gauge readings |
| `rainfall_idf.py` | How much rain counts as unusual, by duration |
| `radar.py` | Rainfall radar frames, mapped onto the grid |
| `hydrology_static.py` | Drainage basins, streams and road markers |
| `road_network.py` | Road geometry, for saying which roads a flood affects |
| `static_context.py`, `signal_rows.py` | The stored shapes the detector reads |

## Thresholds matter here

A gauge without official flood thresholds cannot say whether a reading is high,
so its readings are not stored or evaluated at all. Being in the catalogue is
not the same as being usable.
