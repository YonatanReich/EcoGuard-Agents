# detectors/air_pollution/

Air-quality candidate detection and its compact historical baseline support.

The persisted-observation processor adapts shared `observations` rows, resolves
the exact active `five_minute_observation` baseline, and applies the candidate
rule in `detector.py`. Spatial enrichment and correlation attach evidence to a
suspected anomaly. None of these modules assign severity, route an event,
persist a candidate, or plan a response.

This hazard is **advisory**, so its analyzer belongs under
`ecoguard/analyzers/non_emergency/air_pollution/`, not `emergency/`.
