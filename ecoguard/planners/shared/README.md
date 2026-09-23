# Shared planning

The planning machinery every hazard uses, so fire, flood and the rest produce
plans of the same shape.

| File | What it does |
|---|---|
| `planner.py` | Searches the protocols, asks the model, and checks the answer |
| `schemas.py` | The shape a plan has to take |
| `adapters.py` | Turns each hazard's assessment into the planner's input |

## Fail closed

A plan that cites no protocol, asks for an action no assigned unit can carry
out, or contradicts itself is rejected. The planner then reports that it
produced nothing, rather than passing a plausible-looking plan to an operator.
