# Demo scenarios

The authored datasets a demo runs against.

`demo_a.py` contains a flood, two fires, a pollution episode and a handful of
reports, plus noise that should be ignored.

`demo_b.py` currently contains the first four events of the more demanding
second scenario: an expanding fire crossing a grid boundary, a separate nearby
fire, an escalating flood and an earthquake with two aftershocks. Its noise
targets stale fire observations, a one-reading flood spike and a sub-threshold
earthquake.

Each event was decided first, then written as the readings the real collectors
would have produced for it - right down to each provider's timestamps and
units. That direction matters: the pipeline sees ordinary observations and
nothing about the demo makes detection easier than it is in practice.
