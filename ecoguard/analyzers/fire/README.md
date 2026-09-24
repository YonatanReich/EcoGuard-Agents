# analyzers/emergency/fire/

Everything here is about a fire that exists. `risk_analysis_agent.py` turns a
detected event into a protocol-grounded assessment, citing the corpus in
`response_planner/protocols/` and returning no score rather than a guessed one
when the evidence is missing.

There is deliberately no pre-ignition model. `risk_prediction_agent.py` and the
5 km grid behind it were removed on 2026-09-24: the model artefact was never
committed, so the lane had never produced a number, and nothing in detection,
analysis or spread read it. The terrain it carried is in `surface_cells` at
270 m rather than 5 km. The training scripts remain under `ml/`, which
`scripts/load_surface_grid.py` also reads its raster helpers from.

`fuel_models.py` maps land-cover fractions to Anderson-13 spread parameters —
the translation any spread model needs and no satellite provides.
