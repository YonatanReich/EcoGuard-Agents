# Earthquake analyzer

Turns a reported earthquake into what it means on the ground: how strongly it
would have been felt in each place, and what that is likely to have done.

## What is here

| File | What it does |
|---|---|
| `intensity.py` | How strongly the shaking would be felt at a distance |
| `risk_scale.py` | The published scale that intensity is reported on |
| `impact.py` | What that shaking is likely to have done where people are |
| `incident_handler.py` | The entry point the coordinator calls |

All of it is standard published arithmetic. Nothing here calls a model.
