# Demo

Proving the system works, on evidence we control.

On live data nobody knows what the right answer was, so "it found three fires"
cannot be checked. Here the events are written down first, the evidence is
built backwards from them, and the expected result is recorded before anything
runs. Then the real pipeline runs against it and the output is graded.

Nothing is faked except the observations. The same detectors, coordinator,
analyzers and planners do the work.

## What is here

| File | What it does |
|---|---|
| `sandbox.py` | Builds an isolated copy of the tables the pipeline writes, switches to it, and switches back |
| `scenarios/demo_a.py` | Five authored events, the evidence they would have produced, and the noise the system should ignore |
| `grade.py` | Compares what came out against what was expected |
| `run_once.py` | Seeds, runs one pass and grades it, from the command line |

## Things worth knowing

The isolation is a separate database schema holding only the tables the
pipeline writes. Reference data - towns, stations, guidance - is deliberately
left out so a demo incident is still reasoned about against the real country.

Collectors are paused while a scenario runs, so live data cannot wander in and
be mistaken for seeded evidence.

There is a button for this on the dashboard. The command line does the same
thing without waiting for the next ten-minute cycle.
