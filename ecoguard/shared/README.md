# Shared

Code used by more than one layer.

If something belongs to a single layer it lives with that layer. What is left
here is genuinely cross-cutting: the grid the whole system is addressed by, the
signal and event shapes every stage passes around, and the one place that talks
to Claude.

## What is here

| File | What it is |
|---|---|
| `llm.py` | The single Claude entry point: one structured call, spend guards, token logging |
| `events.py` | The event shape the dashboard reads, for every hazard |
| `signals.py` | The signal shape detectors emit and the coordinator consumes |
| `cells.py`, `grid.py` | The map grid every location is snapped to |
| `protocols.py` | Finding and verifying quotable passages in the guidance corpus |
| `schemas.py` | Shared model output shapes |
| `geocoding.py` | Turning place names into coordinates |
| `activity.py` | What each part of the system is doing right now, for the System page |

## Things worth knowing

Every Claude call in the project goes through `llm.py`. That is why a spending
limit and a prompt-size ceiling can exist at all — there is exactly one door.
