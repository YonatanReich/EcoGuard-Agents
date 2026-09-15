# Environmental wildfire baseline evaluation

## Scope and data

This experiment extends `fire_prediction_ml_dataset_2023_2026.csv` while preserving all 6,736 samples (2,321 positive proxy labels and 4,415 negative proxy labels). It is an offline research baseline and is not connected to production detection, the backend, or the frontend.

The temporal evaluation remains unchanged: 2023–2024 train (3,863 rows; 1,458 positive), 2025 validation (2,002; 778 positive), and partial-2026 test (871; 85 positive). Model and probability-threshold selection use only 2025. The 2026 set is evaluated once after selection.

## Features and provenance

- The existing 23 Open-Meteo weather fields remain strictly pre-event.
- Elevation is from the [Open-Meteo Elevation API](https://open-meteo.com/en/docs/elevation-api), which serves Copernicus DEM GLO-90 data at approximately 90 m resolution. Coordinates are queried in batches and cached in `data/generated/historical_environmental_elevation_cache.json`.
- Calendar context is encoded as sine/cosine of UTC day-of-year and UTC hour. Raw timestamp, month, and year are not model inputs.
- Historical fire context is calculated from the local historical FIRMS candidate file. It includes counts within 5 km/30 days, 10 km/90 days, and 25 km/365 days, plus days since the previous candidate within 10 km. Only candidates with timestamps strictly earlier than the sample timestamp are considered.

Slope is omitted because a single elevation query cannot derive it reliably. Land cover/vegetation is omitted because the repository has no authoritative local raster cache and the existing OSM agent does not produce a vegetation value. Historical FWI is omitted because the current fire-danger agent requests a current-date WMS layer and cannot reliably reconstruct historical values. These omissions are explicit; no values are fabricated.

Elevation is available for all 6,736 rows. The prior-fire interval is null for 57 rows with no earlier FIRMS candidate within 10 km. Land-cover and historical-FWI status fields report their unavailable state for every row.

## Leakage controls

The model allowlist excludes coordinates, settlements and LAMAS codes, labels and provenance, official monthly counts, FIRMS FRP/hotspot/satellite fields, and timestamp as a raw feature. Latitude/longitude are used only to obtain elevation and query past spatial history. Current and future FIRMS observations are excluded. Preprocessing is fitted on training data only.

One important scientific caveat remains: proxy negatives were created using FIRMS exclusion rules. Consequently, historical-FIRMS-density features may partly learn the negative-sampling procedure even though they are temporally leakage-safe. This must be treated as possible sampling bias, not causal fire evidence.

## Distribution shift

The largest train-to-partial-2026 standardized median differences were day-of-year sine (+0.954), day-of-year cosine (-0.567), 3-day maximum temperature (-0.518), prior FIRMS candidates within 25 km/365 days (+0.481), 24-hour maximum temperature (-0.426), 3-hour temperature (-0.350), and 6-hour temperature (-0.347). Partial-year season coverage is therefore a major source of shift. These diagnostics do not influence fitting or normalization.

## Validation selection

At threshold 0.50, the full feature set produced the following 2025 ranking:

| Model | ROC-AUC | PR-AUC | Selected threshold | F1 at selected threshold |
|---|---:|---:|---:|---:|
| Dummy | 0.500 | 0.389 | 0.375 | 0.560 |
| Logistic regression | 0.663 | 0.584 | 0.430 | 0.584 |
| Random forest | 0.699 | 0.611 | 0.350 | 0.613 |
| HistGradientBoosting | 0.721 | 0.639 | 0.380 | 0.628 |

HistGradientBoosting with threshold 0.380 was selected using validation PR-AUC first, then selected-threshold F1 and recall.

## Untouched 2026 results and ablations

| Feature group | ROC-AUC | PR-AUC | Precision | Recall | F1 | Brier | Predicted positive | TN / FP / FN / TP |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Weather only | 0.367 | 0.095 | 0.088 | 0.871 | 0.161 | 0.256 | 96.1% | 23 / 763 / 11 / 74 |
| Weather + season | 0.543 | 0.155 | 0.100 | 0.835 | 0.179 | 0.236 | 81.5% | 147 / 639 / 14 / 71 |
| Weather + elevation | 0.632 | 0.237 | 0.104 | 0.882 | 0.185 | 0.233 | 83.1% | 137 / 649 / 10 / 75 |
| Weather + prior FIRMS history | 0.649 | 0.447 | 0.110 | 0.659 | 0.188 | 0.212 | 58.6% | 332 / 454 / 29 / 56 |
| Full | 0.670 | 0.430 | 0.117 | 0.718 | 0.202 | 0.214 | 59.7% | 327 / 459 / 24 / 61 |

The full baseline improves materially over weather-only ranking and calibration, but precision remains low. Prior-fire history supplies most of the added ranking signal; the full model trades a little PR-AUC against the history-only ablation for higher recall and ROC-AUC. This is not production-ready.

## Predictive associations

Validation-set permutation importance for the selected model ranks: prior candidates within 5 km/30 days, days since a prior candidate within 10 km, UTC hour cosine/sine, prior candidates within 10 km/90 days, elevation, and UTC day-of-year sine. The complete ranking is exported to `fire_prediction_environmental_feature_importance.csv`. These are predictive associations and are not evidence of causation.

## Geographic and scientific limitations

Static elevation and history features work at arbitrary coordinates and do not require settlement membership. However, the 2026 unlocated subset contains 134 negatives and zero positives, so performance on real positive open/rural fires cannot be measured. Positive labels mean FIRMS candidates with same-settlement/month official support, not individually confirmed incidents; negatives mean absence of a nearby FIRMS candidate under the configured proxy rule. The partial-2026 test has only 85 positives and does not cover a full seasonal cycle.

## Reproduction

Build or resume the environmental dataset:

```powershell
.\.ml-venv\Scripts\python.exe -m scripts.build_historical_environmental_features
```

Retrain and write the evaluation artifacts:

```powershell
.\.ml-venv\Scripts\python.exe -m scripts.train_fire_prediction_environmental_models
```
