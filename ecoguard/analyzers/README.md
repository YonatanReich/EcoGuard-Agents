# Analyzers

The step that works out how serious something is.

The coordinator says a fire exists. An analyzer says how bad it is, what is
nearby, and what is still unknown. It never decides what to do about it — that
is the planner's job — and it never goes looking for new events.

Every analyzer is expected to say what it could *not* determine. A missing
number is reported as missing rather than filled in with a plausible one.

## What is here

One folder per hazard.

| Folder | What it works out |
|---|---|
| `fire/` | How severe a detected fire is, how it may spread, what it threatens, and a separate machine-learning estimate of where fires are likely to start |
| `flood/` | Severity from official discharge thresholds, and which roads are affected |
| `earthquake/` | An estimated impact area and the settlements inside it |
| `air_pollution/` | How unusual a reading is, where the pollution may drift, and who lives in the way |
| `water_level/` | A plain advisory about the lake level |

`fire/ml/` holds the feature building, training and calibration behind the fire
likelihood model. It runs rarely and produces the model files the analyzer
loads.

## Things worth knowing

Only the fire analyzer uses a language model. Flood, earthquake, air pollution
and water level are ordinary calculations, which is why their results are
reproducible and testable without a model.
