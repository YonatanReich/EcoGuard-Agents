# Fire model training

The offline half of fire risk: building the training data and fitting the
models. None of this runs in the live system - it produces the model files the
live system reads.

Run in order, roughly: build the record of real fires, generate matching
examples of nothing happening, add the weather and terrain that preceded each
one, then train and calibrate.

## What is here

| File | What it does |
|---|---|
| `build_firms_fire_rescue_ground_truth.py` | Matches satellite detections to official fire records |
| `build_historical_fire_negative_samples.py` | Generates places and times where nothing was burning |
| `build_historical_fire_weather_features.py` | Adds the weather that preceded each record |
| `build_historical_landcover_terrain_features.py` | Adds terrain and what grows there |
| `build_historical_environmental_features.py` | Adds fire history for the same places |
| `train_fire_prediction_*.py` | Trains the models and the cut-down versions they are compared against |
| `calibrate_fire_risk_levels.py` | Corrects the scores and sets the low/medium/high boundaries |

## The rule that matters

Every input is taken from before the moment being predicted, and the data is
split by time rather than at random. A random split lets tomorrow teach the
model about today, and the score that produces is not real.
