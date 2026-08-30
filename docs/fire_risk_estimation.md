# Fire Risk Estimation

## Product meaning

`FireRiskPredictionAgent` estimates how strongly a complete set of current conditions resembles conditions associated with historical fire occurrence. It returns a continuous score and `low`, `medium`, or `high`. The score is **not** a guaranteed fire probability and is not evidence that a fire exists.

The system boundaries remain separate:

- Prediction agent: prepared current conditions → estimated fire risk.
- FIRMS/Telegram detection: observations or reports that may evidence an actual event.
- Risk Analysis (Developer B): analyzes an already detected incident.
- Resource Allocation/Response Planning (Developer C): recommends operational resources and response.

This work does not connect the prediction agent to an API, scheduler, dashboard, map, or alerting system.

## Model and calibration

The base artifact is `data/generated/ml/fire_prediction_landcover_terrain_model.joblib`, a 44-predictor `HistGradientBoostingClassifier` trained on 2023–2024. It was not retrained. The 2025 rows alone were used for calibration and threshold selection; partial-2026 remained untouched until final evaluation.

Calibration methods were compared with deterministic five-fold out-of-fold predictions on 2025:

| Method | Brier | 10-bin ECE | ROC-AUC | PR-AUC |
|---|---:|---:|---:|---:|
| Raw | 0.2166 | 0.1207 | 0.7298 | 0.6395 |
| Sigmoid | 0.2007 | 0.0616 | 0.7290 | 0.6389 |
| Isotonic | 0.1944 | 0.0335 | 0.7189 | 0.6174 |

Sigmoid calibration was selected. Although isotonic had the lowest apparent out-of-fold calibration error, it reduced validation PR-AUC by more than 0.01 through tied score steps. The reproducible rule selects the lowest-Brier method whose ROC-AUC and PR-AUC are both within 0.01 of raw ranking performance. The final sigmoid mapping was then fitted on all 2025 rows. This preserves the base ranking while improving validation reliability.

On untouched partial-2026, sigmoid scores have Brier 0.1369 and 10-bin ECE 0.2286. The high ECE demonstrates temporal calibration drift: the score should be treated as a relative risk index, not a literal event probability.

## Risk boundaries

- LOW/MEDIUM: `0.2824200248`
- MEDIUM/HIGH: `0.4354667587`

Both boundaries use only 2025 out-of-fold sigmoid scores. HIGH maximizes validation F1 subject to no more than 30% of validation rows being HIGH. The LOW/MEDIUM boundary is the highest score retaining at least 90% of validation positives in MEDIUM+HIGH. Boundary values belong to the higher level.

### Bucket evaluation

| Split / level | Rows | Positives | Positive prevalence | Share of all positives | Mean score | Min–max |
|---|---:|---:|---:|---:|---:|---:|
| 2025 LOW | 543 | 77 | 14.2% | 9.9% | 0.171 | 0.017–0.282 |
| 2025 MEDIUM | 864 | 354 | 41.0% | 45.5% | 0.357 | 0.282–0.435 |
| 2025 HIGH | 595 | 347 | 58.3% | 44.6% | 0.633 | 0.435–0.908 |
| 2026 LOW | 350 | 26 | 7.4% | 30.6% | 0.162 | 0.018–0.282 |
| 2026 MEDIUM | 341 | 21 | 6.2% | 24.7% | 0.351 | 0.283–0.432 |
| 2026 HIGH | 180 | 38 | 21.1% | 44.7% | 0.567 | 0.436–0.879 |

Validation prevalence is monotonic. Partial-2026 is not fully monotonic because MEDIUM prevalence (6.2%) is slightly below LOW (7.4%); HIGH remains distinctly enriched (21.1%). This distribution shift is reported rather than concealed.

For 2026, LOW/MEDIUM/HIGH burdens are 40.2% / 39.2% / 20.7%. HIGH captures 44.7% of positives; MEDIUM+HIGH captures 69.4%. HIGH contains 142 false positives (78.9% of HIGH alerts, or 18.1% of all 786 negatives). MEDIUM+HIGH contains 462 false positives (88.7% of those alerts, or 58.8% of negatives). These figures reflect proxy labels and must not be interpreted as operational false alarms without prospective validation.

## Agent contract

Input is a mapping containing exactly the 44 feature names stored in `fire_risk_thresholds.json`. Values must be numeric. Missing and unknown fields are rejected. NaN is passed through because the saved sklearn pipeline supports missing numeric values; infinity is rejected. The model artifact and calibration metadata must have identical feature names and order.

Successful output:

```json
{
  "status": "ok",
  "risk_score": 0.57,
  "risk_level": "high",
  "model_version": "landcover-terrain-YYYY-MM-DD",
  "risk_semantics": "estimated_fire_risk",
  "main_factors": [
    {
      "feature": "fires_within_5km_previous_30d",
      "statement": "Recent historical fire activity nearby was associated with the model output."
    }
  ]
}
```

Errors are structured with `status: error`, null score/level, and an error code. Main factors combine existing validation permutation importance with whether an input falls outside its 2023–2024 interquartile range. They are model-associated factors, not causal explanations.

## Strong-event case studies

The independent Tier B events were not used for calibration or thresholds. They do not currently have complete rows containing all 44 pre-event weather, historical-density, WorldCover, elevation, and slope predictors. Constructing those rows requires additional historical feature acquisition, so no scores were fabricated and no network collection was launched in this task.

## Reproduction

Regenerate calibration metadata:

```powershell
.\.ml-venv\Scripts\python.exe -m scripts.calibrate_fire_risk_levels
```

Score one prepared feature JSON object containing exactly all 44 fields:

```powershell
.\.ml-venv\Scripts\python.exe -m agents.fire_risk_prediction_agent .\prepared_fire_risk_features.json
```

The generated `data/generated/ml/fire_risk_thresholds.json` stores the feature order, thresholds, sigmoid parameters, selection rules, evaluation summaries, training references, sklearn version, paths, and semantics.

## Scientific limitations

Labels remain FIRMS-derived positives with monthly official support and proxy negatives; neither class is absolute event truth. Partial-2026 is small and shifted, its unlocated subset lacks positive examples, and calibration drift is substantial. Risk buckets are relative operating bands derived from one validation year. They require prospective validation before operational alerting. No causal claims should be made from factor descriptions or feature importance.
