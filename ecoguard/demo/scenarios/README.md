# Demo scenarios

The authored datasets a demo runs against.

`demo_a.py` contains a flood, two fires, a pollution episode and a handful of
reports, plus noise that should be ignored.

`demo_b.py` contains eight events in the more demanding second scenario: an
expanding fire crossing a grid boundary, a separate nearby fire, an escalating
flood, an earthquake with two aftershocks, a distant concurrent earthquake, an
air-pollution advisory, a same-origin forwarded fire claim and a text report
that should join a satellite fire. Its initial noise targets stale fire
observations, a one-reading flood spike and a sub-threshold earthquake.

The two text scenarios intentionally remain honest about service availability.
They enter as raw Telegram observations and are never pre-classified by the
scenario. With Claude unavailable, the keyword fallback has no location and
cannot complete B7 or attach the report portion of B8.

Each event was decided first, then written as the readings the real collectors
would have produced for it - right down to each provider's timestamps and
units. That direction matters: the pipeline sees ordinary observations and
nothing about the demo makes detection easier than it is in practice.
