# Scripts

One-off and occasional jobs, run by hand.

Nothing here runs on a timer. These build the reference data the system reads,
import static datasets, or check that things are working.

## What is here

Roughly three kinds:

**Preparing data the system needs** - loading town boundaries, the map grid,
population, road networks, fire districts, station rosters, and the guidance
corpus.

**Building things that are computed once** - weather and satellite baselines,
the fire risk grid.

**Checking** - `preflight.py` says whether this machine is ready to run a live
demonstration. `claude_smoke_check.py` is retained as documentation of the
retired point-query model flow; it is not part of the runnable system.

## Things worth knowing

Run `preflight.py` before any live demonstration. It checks the things the
application cannot report about itself: whether the database answers, whether
the Claude key still works, whether another copy is already running, and which
collectors have gone quiet.
