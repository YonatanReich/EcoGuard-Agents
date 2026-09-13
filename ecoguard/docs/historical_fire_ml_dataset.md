# Historical positive/negative weather dataset

This stage applies the existing historical Open-Meteo feature implementation
to FIRMS-excluded proxy negatives and then combines positive and negative rows
into one ML-ready schema. It does not train a model or calculate FWI.

## Reused weather semantics

The negative weather builder imports the existing endpoint, variables, UTC
parser, response validation, retry policy, checkpoint implementation, and
`compute_features()` function from
`scripts/build_historical_fire_weather_features.py`. It does not maintain a
second weather calculation.

For negatives, `sample_timestamp` is adapted to the existing event reference
time and `latitude`/`longitude` are adapted to the existing centroid request
coordinates. Features retain the same:

- Open-Meteo Archive endpoint and hourly variables
- explicit UTC handling
- 1, 3, 6, and 12-hour lag rules
- 24-hour, 3-day, and 7-day half-open windows
- strict exclusion of provider timestamps at or after the reference time
- missing/partial/unavailable/failed status behavior
- bounded retry and backoff behavior

## Negative checkpoint and resume

Negative responses are cached separately under:

`data/generated/historical_fire_negative_weather_checkpoint/`

Each proxy negative is adapted to the existing checkpoint identity:

- `candidate_id = negative_id`
- `start_timestamp = sample_timestamp`
- `centroid_latitude = latitude`
- `centroid_longitude = longitude`

The existing manifest compatibility checks and per-entry SHA-256 integrity
checks apply. Successful, partial, and unavailable responses resume without a
new request. Failed provider requests remain eligible for a later retry.

Start or resume negative weather collection:

```console
python -m ecoguard.scripts.build_historical_negative_weather_features
```

## Label semantics

- Positive `fire_label=1` and
  `label_source=firms_candidate_with_official_month_support` mean a FIRMS
  candidate exists and a relevant Fire and Rescue monthly aggregate exists in
  that settlement/month. This does not establish individual incident identity.
- Negative `fire_label=0` and `label_source=firms_proxy_negative` mean no FIRMS
  candidate was observed inside the configured 5 km / expanded 72-hour
  exclusion rule. This is a proxy negative, not proof that no fire existed.

## Unified dataset

After negative weather collection finishes:

```console
python -m ecoguard.scripts.build_fire_prediction_ml_dataset
```

Output:

`data/generated/fire_prediction_ml_dataset_2023_2026.csv`

Common identity and provenance fields are followed by the exact shared weather
feature tuple from the positive builder. The declared ML feature list contains
only these weather features. FIRMS post-detection values such as FRP, hotspot
count, FIRMS confidence, satellite, instrument, and source product are not
included in the unified schema or ML feature list.

The assembler rejects non-supported positive inputs, nonzero negative labels,
duplicate sample IDs, duplicate timestamp/coordinate rows, incompatible
schemas, and any FIRMS leakage field added to the declared feature list.

Rows with failed, partial, or unavailable weather remain in the output with
empty features and an explicit safe status; they are not silently dropped.
