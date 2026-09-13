# research/

One-off scripts that produced the ML artefacts and evaluation datasets under
`data/generated/` and `data/evaluation/`. They are not part of the runtime
pipeline and are excluded from the default `pytest` run (`pytest.ini` pins
`testpaths = tests`). Run them from the repository root, e.g.
`python -m research.training.train_fire_prediction_models`.

They are kept because they are the evidence of method for the academic writeup.

## datasets/ — historical dataset construction (Jul–Aug 2025)

| Script | Produced |
|---|---|
| `build_historical_firms_dataset.py` | Raw FIRMS archive pull for the study period. |
| `build_firms_fire_rescue_ground_truth.py` | FIRMS hotspots matched against Fire & Rescue incident records. |
| `build_historical_fire_ground_truth.py` | Positive wildfire labels from the matched incidents. |
| `build_strong_historical_wildfire_ground_truth.py` | Stricter positive set (large/confirmed wildfires only). |
| `build_historical_fire_negative_samples.py` | Negative samples drawn away from any known fire. |
| `build_historical_fire_weather_features.py` | Weather features at each positive sample's ignition time. |
| `build_historical_negative_weather_features.py` | The same features for the negative samples. |
| `build_historical_environmental_features.py` | Prior-FIRMS density and other environmental features. |
| `build_historical_landcover_terrain_features.py` | Land-cover class, slope and terrain features from raster tiles. |
| `build_fire_prediction_ml_dataset.py` | Joined positive + negative feature matrix used for training. |
| `build_historical_forecast_ml_pilot_dataset.py` | Forecast-horizon variant of the dataset for the pilot. |
| `build_historical_telegram_wildfire_pilot.py` | Telegram message corpus labelled against wildfire ground truth. |
| `build_israel_location_cache.py` | `data/israel_locations.json` geocoding cache. |

## training/ — model fitting and calibration (Aug 2025)

| Script | Produced |
|---|---|
| `train_fire_prediction_models.py` | Baseline weather-only models; metric and threshold selection helpers reused by the others. |
| `train_fire_prediction_environmental_models.py` | Models with environmental features added. |
| `train_fire_prediction_landcover_terrain_models.py` | Final model: weather + environmental + land-cover/terrain. Defines `FULL_FEATURES`, the feature order the runtime agent depends on. |
| `calibrate_fire_risk_levels.py` | `data/generated/ml/fire_risk_thresholds.json`, the score→level cut points. |

## evaluation/ — response-plan evaluation harness (Sep 2025)

| Script | Produced |
|---|---|
| `build_evaluation_cases.py` | The eight synthetic fire cases in `data/evaluation/fire_cases/`. |
| `run_response_plan_evaluation.py` | Runs the planner over those cases and scores it with the judge agent. |
| `evaluation_schemas.py` | `PlanVerdict`, `DIMENSION_WEIGHTS`, `case_score` — the judge's scoring contract. |

## pilots/ — exploratory studies (Aug 2025)

| Script | Produced |
|---|---|
| `build_historical_forecast_risk_pilot.py` | Forecast-based risk pilot dataset. |
| `evaluate_historical_forecast_deterioration_pilot.py` | Measured how far ahead forecast-driven risk stays useful. |
| `build_fire_risk_strong_event_case_study.py` | Case study of the model's behaviour on the strong-event subset. |

## tests/

The tests for the above, moved alongside them. Run explicitly:
`pytest research/tests`.

## Runtime code that still imports from here

Four runtime modules depend on definitions in these files. Moving or renaming
them will break the running system:

- `ecoguard/analyzers/emergency/fire/risk_prediction_agent.py` → `training.calibrate_fire_risk_levels.apply_calibration`
- `ecoguard/response_planner/fire/plan_judge.py` → `evaluation.evaluation_schemas`
- `ecoguard/analyzers/emergency/fire/feature_builder.py` → `datasets.build_historical_environmental_features`, `datasets.build_historical_fire_negative_samples`
- `ecoguard/analyzers/emergency/fire/static_feature_store.py` → `datasets.build_historical_landcover_terrain_features`
