# Demo scenarios

The authored datasets a demo runs against.

`demo_a.py` is the main one: a flood, two fires, a pollution episode and a
handful of reports, plus noise that should be ignored.

Each event was decided first, then written as the readings the real collectors
would have produced for it - right down to each provider's timestamps and
units. That direction matters: the pipeline sees ordinary observations and
nothing about the demo makes detection easier than it is in practice.
