# Data

Everything the system reads but does not produce itself.

## What is here

| Folder | What it holds |
|---|---|
| `protocols/` | The written emergency guidance the planners must cite, one folder per hazard, plus the tools that split it into quotable passages |
| `reference/` | Committed reference data: the service area, town boundaries and population, station rosters |
| `evaluation/` | Hand-written test cases used to check the fire analysis |
| `generated/` | Machine output: trained models, cached rasters, derived files. Everything here can be rebuilt by a script, and none of it is a source of truth |

## Things worth knowing

`generated/` is ignored by version control on purpose. If something in there is
missing, a script under `ecoguard/scripts` rebuilds it.

The protocol corpus is the reason plans can be checked. A planner may only quote
passages that actually appear here, and every quotation is verified against the
original text before the plan is accepted.
