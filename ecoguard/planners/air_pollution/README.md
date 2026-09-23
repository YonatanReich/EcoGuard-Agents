# Air pollution planner

Turns a finished pollution assessment into advice: who should be told, what
they should be told, and over what area.

Advisory rather than emergency - nobody is dispatched for an air-quality
episode, so the output is warnings and recommendations rather than units.

| File | What it does |
|---|---|
| `planner.py` | Produces the advice, grounded in the protocol documents |
| `schemas.py` | The shape the advice has to take |

The planner is deliberately shown a trimmed version of the assessment. The full
one carries every detector reading behind the episode, and sending all of it
was once the single largest cost in the system.
