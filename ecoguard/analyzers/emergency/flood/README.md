# analyzers/emergency/flood/

`event_analyzer.py` deterministically analyzes the hydrometric Flood evidence
already persisted on a Coordinator incident. It produces the latest state per
station, an observed discharge trend, and an explicit change classification:
`initial`, `escalated`, `deescalated`, `updated`, or `no_material_change`.

Crossing an official Q threshold is a material severity change. A new station
or cell is a material footprint update. Another reading inside the same Q band
and footprint is retained as evidence but does not ask downstream planning and
allocation to run again.

The analyzer does not detect events, infer inundation, plan a response, allocate
resources, or call a language model. `event_analysis_schemas.py` is its strict
typed boundary. Runtime integration with `incident_handler.py` is separate.
