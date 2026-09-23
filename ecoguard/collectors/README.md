# Collectors

Everything that reaches out to the outside world.

Each collector wakes on its own timer, asks one provider for whatever is new,
and writes what it gets into the observations table. That is all it does. A
collector never decides whether something is happening, never calls another
collector, and never returns anything to a caller — the rest of the system
reads what it wrote.

The timers themselves live in `ecoguard/scheduler.py`, not here, and each
interval is set by how often that provider actually publishes.

## What is here

| Folder | Where the data comes from |
|---|---|
| `fire/` | NASA satellite hotspots, European fire-weather ratings, vegetation imagery, and the daily fire-danger index |
| `flood/` | Israel Water Authority stream gauges and their official flood thresholds |
| `earthquake/` | Geological Survey of Israel earthquake feed |
| `pollution/` | Ministry of Environmental Protection air-quality monitoring stations |
| `water_level/` | Lake Kinneret water level |
| `text/` | Israeli news RSS feeds |
| `shared/` | Used by more than one lane: weather (observations and forecasts) and the Telegram reader |

## Things worth knowing

A collector that is missing its credentials is not scheduled at all, rather
than failing every few minutes forever.

Collectors are paused automatically while a demo scenario is running, so live
data cannot leak into a controlled test.
