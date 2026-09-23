# Coordinator

The step that turns signals into *things that are happening*.

Detectors produce a stream of signals, and the same event usually produces
several — three satellite passes over one fire, a gauge reading every ten
minutes, two people posting about the same smoke. The coordinator folds all of
that into one incident per event, so an operator sees one fire rather than
eleven readings.

It also decides which queue an incident belongs in: emergency (fire, flood,
earthquake) or advisory (air quality, fire weather, lake level).

## What is here

| File | What it does |
|---|---|
| `agent.py` | One pass: close what has gone quiet, fold new signals into incidents, route them |
| `incidents.py` | Reading and writing incidents, including merging and closing them |
| `matching.py` | Whether a new signal belongs to an incident already open, and how long each hazard stays open after its last signal |
| `dispatcher.py` | Hands each touched incident to the right handler, and decides when a plan is stale enough to redo |
| `event_projection.py` | Turns a finished result into the event the dashboard reads |
| `queues.py` | Which queue each hazard belongs to |

## Things worth knowing

A plan is not rebuilt just because a new signal arrived. Air quality episodes
can produce hundreds of signals in a day, and rebuilding the advice for each
one costs real money for no new information.

An incident resting only on unconfirmed reports is routed differently from one
backed by an instrument, and it says so.
