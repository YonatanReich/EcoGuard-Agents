# Land-cover and terrain wildfire baseline

## Scope

This offline experiment adds static land cover and terrain slope to all 6,736 rows of `fire_prediction_ml_environmental_dataset_2023_2026.csv`. It does not alter production detection, backend, frontend, or response logic.

The evaluation remains identical to the earlier baseline: train on 2023–2024, select the model and threshold using 2025 only, and evaluate once on partial-2026. The four model families and their fixed configurations are unchanged.

## Authoritative static sources

Land cover uses [ESA WorldCover 2021 v200](https://esa-worldcover.org/en/data-access), a global 10 m product based on Sentinel-1 and Sentinel-2 and licensed CC BY 4.0. Three official 3° Cloud-Optimized GeoTIFF map tiles cover the sample coordinates. The raw official class codes are preserved, and the 11 published classes are represented by a compact 11-column one-hot encoding.

Terrain uses [Copernicus DEM GLO-90](https://copernicus-dem-90m.s3.amazonaws.com/readme.html), a global approximately 90 m digital surface model. Slope is calculated in degrees with the Horn 3×3 finite-difference method, using latitude-adjusted east-west cell size. Neighborhood cells are resolved across 1° tile boundaries; slope is never derived from a single elevation point. Aspect is omitted.

The acquisition contains three WorldCover tiles and nine GLO-90 tiles totalling 128,805,447 bytes. Coordinate results are cached in `data/generated/historical_landcover_terrain_cache.json` (4,642 unique coordinates). The cache and final CSV are generated and ignored by Git.

## Completeness and encoding

All 6,736 rows are preserved. Land cover and slope have zero missing values. Eight WorldCover classes occur in the samples: built-up, cropland, grassland, tree cover, bare/sparse vegetation, permanent water, shrubland, and herbaceous wetland. Snow/ice, mangroves, and moss/lichen remain valid zero-valued one-hot columns because those official classes do not occur at the sampled coordinates.

Raw provenance fields (`land_cover_source_code`, `land_cover_source_class`, and collection statuses) are retained but are not model inputs. The added predictors are the 11 one-hot fields and `slope_degrees`.

## Leakage controls

Land cover and DEM values are static and independent of fire labels and post-event observations. Coordinates are used only for raster lookup. Coordinates, settlements, LAMAS codes, official monthly aggregates, label provenance, current-event FIRMS variables, and post-event data remain excluded. Existing weather and historical-FIRMS features retain their prior strict pre-event semantics.

## Ablation results

Validation-selected metrics are:

| Feature set | Selected model | Threshold | ROC-AUC | PR-AUC | Precision | Recall | F1 | Brier | Predicted positive | TN / FP / FN / TP |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Current enriched | HistGradientBoosting | 0.380 | 0.721 | 0.639 | 0.481 | 0.902 | 0.628 | 0.218 | 72.8% | 468 / 756 / 76 / 702 |
| + land cover | HistGradientBoosting | 0.420 | 0.723 | 0.635 | 0.499 | 0.856 | 0.631 | 0.218 | 66.6% | 556 / 668 / 112 / 666 |
| + slope | HistGradientBoosting | 0.415 | 0.721 | 0.635 | 0.500 | 0.879 | 0.638 | 0.219 | 68.3% | 541 / 683 / 94 / 684 |
| + land cover + slope | HistGradientBoosting | 0.445 | 0.730 | 0.640 | 0.518 | 0.829 | 0.638 | 0.217 | 62.2% | 624 / 600 / 133 / 645 |

Untouched partial-2026 results are:

| Feature set | ROC-AUC | PR-AUC | Precision | Recall | F1 | Brier | Predicted positive | TN / FP / FN / TP |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Current enriched | 0.670 | 0.430 | 0.117 | 0.718 | 0.202 | 0.214 | 59.7% | 327 / 459 / 24 / 61 |
| + land cover | 0.677 | 0.438 | 0.116 | 0.635 | 0.196 | 0.213 | 53.6% | 373 / 413 / 31 / 54 |
| + slope | 0.674 | 0.449 | 0.116 | 0.659 | 0.198 | 0.217 | 55.3% | 360 / 426 / 29 / 56 |
| + land cover + slope | 0.670 | 0.436 | 0.123 | 0.612 | 0.204 | 0.216 | 48.7% | 414 / 372 / 33 / 52 |

The full static-feature model wins narrowly on 2025 PR-AUC and F1 and therefore remains the correctly selected experiment. On 2026 it substantially reduces false positives (459 to 372) and slightly improves precision/F1, but sacrifices recall. It does not materially improve ROC-AUC over the existing enriched baseline. Slope alone has the strongest 2026 PR-AUC (0.449), but that test observation was not used for selection.

## Feature importance and sanity audit

Validation permutation importance ranks prior FIRMS activity within 5 km/30 days first, days since prior activity second, built-up land cover sixth, and slope seventh. Tree cover ranks 19th; grassland 23rd; cropland 24th; shrubland 26th; permanent water 28th. These are predictive associations, not causal effects.

Class balance across the complete dataset varies but no land-cover class determines the target: built-up has a 45.9% positive rate, bare/sparse vegetation 35.3%, grassland 33.0%, cropland 27.3%, tree cover 26.8%, shrubland 26.5%, wetland 27.3%, and permanent water 6.5%. This pattern warrants caution: positive and proxy-negative generation can produce geographic sampling differences, especially over water and urban areas. The modest model improvement and low individual land-cover importances do not suggest a single category is acting as a near-perfect label proxy.

## Open-area and scientific limitations

Raster lookup succeeds independently of settlement membership, including all unlocated coordinates. In the 2026 unlocated group there are 134 negatives and no positives; the model produces 98 true negatives and 36 false positives there. Recall and PR-AUC cannot be measured without positive unlocated/open-area test examples.

WorldCover 2021 is a static snapshot applied to 2023–2026 and may not reflect later land-cover changes. GLO-90 is a digital surface model, so buildings and vegetation can influence derived urban slope. Raster positional uncertainty and mixed pixels remain. Labels are still FIRMS/official-support proxies, and historical-FIRMS features may encode parts of the proxy-negative sampling process. Historical FWI remains a future enhancement because the current repository source is current-date only.

## Reproduction

```powershell
.\.ml-venv\Scripts\python.exe -m scripts.build_historical_landcover_terrain_features
.\.ml-venv\Scripts\python.exe -m scripts.train_fire_prediction_landcover_terrain_models
```
