# analyzers/emergency/fire/

Two different questions, deliberately separate:

**Given a fire that exists** — `risk_analysis_agent.py` turns a detected event
into a protocol-grounded assessment, citing the corpus in
`response_planner/protocols/` and returning no score rather than a guessed one
when the evidence is missing.

**Given no fire at all** — `risk_prediction_agent.py` scores conditions
nationwide on the 5 km grid, with `feature_builder.py` (44 predictors),
`static_feature_store.py`, `national_scan.py` and `refresh_orchestrator.py`
around it. This is forecasting, not response.

`fuel_models.py` maps land-cover fractions to Anderson-13 spread parameters —
the translation any spread model needs and no satellite provides.
