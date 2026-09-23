# Planners

The step that says what should be done about it.

A planner takes a finished analysis and produces decision support: which *kinds*
of unit are needed and what actions to take in what order. It never picks a
particular station, vehicle or crew — that is the resource allocator — and it
never claims anyone has been dispatched.

Everything a planner recommends has to be traceable to a written protocol. If it
cannot quote the source, the plan is rejected rather than shown.

## What is here

| Folder | What it plans for |
|---|---|
| `shared/` | The emergency planner used by fire, flood and earthquake, plus the input contract they all adapt to |
| `air_pollution/` | Advisory recommendations, copied word for word from reviewed guidance |
| `uncorroborated/` | What to do about a report nobody has confirmed: who to phone. No model call at all |
| `fire/` | The original fire-specific planner, still used by the older single-event endpoint |

The protocol documents themselves live in `ecoguard/data/protocols`.

## Things worth knowing

The uncorroborated planner is deliberately not a model. It names a police
station and a local authority with their phone numbers, straight from the
database, so it is free to run, works when nothing else does, and cannot invent
a number.

A plan that fails its grounding check is retried a few times with increasing
gaps, then left alone. Retrying forever was once a genuine and expensive bug.
