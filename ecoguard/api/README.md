# API

What the dashboard talks to.

A thin layer: it reads what the pipeline already produced and returns it. The
only endpoints that make the system *do* something are the pipeline switch, the
scenario controls and the developer-only collector trigger.

## What is here

| File | What it serves |
|---|---|
| `main.py` | Application startup, map reference data (stations, towns, fire danger), and the older single-point fire query |
| `events.py` | The event feed the dashboard map reads |
| `pipeline.py` | Start and pause detection, analysis and planning, without stopping collection |
| `scenario.py` | Start, stop and grade a controlled demo scenario |
| `demo.py` | Pre-made example events from a separate database, for screenshots |
| `weak_events.py` | The older unconfirmed-report feed, now superseded |
| `area_schemas.py`, `fire_risk_schemas.py` | Request and response shapes |

## Things worth knowing

Starting the application also starts the collection timers, so running two
copies against one database doubles the work and the cost. Run one.

Collection and everything downstream are on separate switches. Collectors run
whenever the process is up, because what they miss is gone for good; detection
onwards can be paused and caught up later, because it reads from the store.
`POST /api/pipeline` flips it while running — a restart would work too, but it
resets every collector's timer, which is the thing pausing was meant to avoid.

Air quality events are filtered before they reach the map: an episode that does
not meet the publication policy is deliberately withheld, which is why the feed
can be shorter than the incident list.
