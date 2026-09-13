# Baseline pre-event weather model evaluation

## Question and leakage boundary

This experiment asks whether pre-event weather features alone distinguish
supported FIRMS candidates from FIRMS-excluded proxy negatives. It does not
change production detection or train on location, identity, provenance, or
post-detection FIRMS evidence.

The allowlist is the exact 23-field `FEATURE_FIELDS` tuple produced by the
historical weather builder. Coordinates, settlement, timestamps, monthly
official counts, label provenance, FRP, hotspot count, confidence, satellites,
and FIRMS products are excluded from model inputs.

## Temporal split

| Split | Years | Negative | Positive | Total |
|---|---|---:|---:|---:|
| Train | 2023–2024 | 2,405 | 1,458 | 3,863 |
| Validation | 2025 | 1,224 | 778 | 2,002 |
| Test | partial 2026 | 786 | 85 | 871 |

The latest train timestamp is before the earliest validation timestamp, and
the latest validation timestamp is before the earliest test timestamp.
Preprocessing is contained in sklearn pipelines and is fit only on training
rows.

## Selection rule

Four small sklearn-native baselines are fit once: prior DummyClassifier,
balanced LogisticRegression, balanced-subsample RandomForestClassifier, and
balanced HistGradientBoostingClassifier. No hyperparameter sweep is performed.

For each model, the probability threshold is selected on 2025 only from 0.10
through 0.90 in 0.005 steps. The rule maximizes F1, then minimizes the absolute
precision/recall difference, then prefers a threshold closest to 0.50. Models
are compared by validation PR-AUC first, followed by selected-threshold F1 and
recall. The 2026 probabilities are not used for either choice.

## Validation results

At threshold 0.50:

| Model | Precision | Recall | F1 | ROC-AUC | PR-AUC | Brier |
|---|---:|---:|---:|---:|---:|---:|
| Dummy | 0.000 | 0.000 | 0.000 | 0.500 | 0.389 | 0.238 |
| Logistic regression | 0.408 | 0.647 | 0.500 | 0.532 | 0.421 | 0.256 |
| Random forest | 0.412 | 0.422 | 0.417 | 0.527 | 0.397 | 0.249 |
| Histogram gradient boosting | 0.404 | 0.548 | 0.465 | 0.522 | 0.406 | 0.257 |

Logistic regression was selected because it had the highest validation PR-AUC
(0.421). Its validation-selected threshold was 0.265. At that threshold,
precision was 0.392, recall 0.994, F1 0.563, and it predicted 98.4% of validation
rows positive. This is a warning that F1 optimization strongly favored recall
under the validation class distribution.

## Untouched 2026 test

The partial-2026 positive prevalence is only 9.76% (85 positives), substantially
below validation prevalence. The selected logistic model generalized poorly.

| Threshold | Accuracy | Precision | Recall | F1 | ROC-AUC | PR-AUC | Brier | TN | FP | FN | TP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.50 | 0.505 | 0.078 | 0.376 | 0.129 | 0.367 | 0.095 | 0.256 | 408 | 378 | 53 | 32 |
| 0.265 | 0.111 | 0.088 | 0.871 | 0.161 | 0.367 | 0.095 | 0.256 | 23 | 763 | 11 | 74 |

At the selected threshold, 96.1% of test rows were predicted positive. PR-AUC
(0.095) was slightly below the 2026 positive prevalence baseline (0.0976), and
ROC-AUC was below 0.5. This baseline does not demonstrate useful temporal
generalization from weather alone.

## Geographic audit

At threshold 0.265:

- Mapped: 737 rows, including all 85 positives. Precision 0.104, recall 0.871,
  F1 0.186; confusion matrix TN=17, FP=635, FN=11, TP=74.
- Unlocated/open-area: 134 rows, all proxy negatives. TN=6 and FP=128.

There are no positive unlocated samples. Consequently, real positive open-area
wildfire performance cannot be estimated from this audit; recall, ROC-AUC, and
PR-AUC are undefined for that subgroup.

## Feature rankings

Largest absolute standardized logistic coefficients:

| Feature | Coefficient |
|---|---:|
| `temperature_1h_before` | -0.694 |
| `temperature_3h_before` | 0.672 |
| `humidity_1h_before` | -0.367 |
| `max_temperature_24h` | 0.361 |
| `min_humidity_24h` | 0.286 |
| `humidity_12h_before` | -0.277 |
| `temperature_6h_before` | -0.273 |
| `precipitation_1h_before` | -0.226 |
| `precipitation_sum_7d` | -0.224 |
| `max_wind_speed_24h` | 0.215 |

Largest random-forest impurity importances were `max_temperature_24h`,
`max_temperature_3d`, `precipitation_sum_7d`, `max_wind_speed_3d`, and
`wind_speed_12h_before`. These rankings show model associations and must not be
interpreted as causal fire drivers.

## Scientific limitations

- Positive labels are FIRMS candidates with settlement/month aggregate support,
  not individually confirmed Fire and Rescue incidents.
- Negative labels mean FIRMS non-observation within the configured exclusion
  rule, not proven fire absence.
- Positive and negative sampling procedures differ and can introduce temporal,
  spatial, and selection biases even though geography is excluded as a feature.
- Open-Meteo values are gridded reanalysis rather than incident-site sensors.
- 2026 is partial and contains only 85 positives, with substantial prevalence
  shift from training and validation.
- Threshold optimization on one validation year can overfit that year's class
  balance and weather distribution.
- This baseline shows that the current weather-only feature/label construction
  is not sufficient for reliable deployment.

Exact machine-readable results are in
`data/generated/ml/fire_prediction_metrics.json`.
