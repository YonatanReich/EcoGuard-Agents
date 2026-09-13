# Historical FIRMS-excluded proxy-negative samples

This stage produces deterministic proxy-negative examples for later wildfire
ML work. It does not train a model, collect weather, or calculate FWI.

## Label definition

`fire_label=0` means:

> No historical FIRMS candidate incident was observed within both the
> configured spatial radius and the candidate incident's expanded temporal
> interval.

It does not prove that no fire existed. FIRMS can miss small, obscured,
short-lived, or otherwise undetectable fires. Therefore these rows are proxy
negatives, not absolute no-fire ground truth. They must not be described as
confirmed negatives.

## Inputs

- Supported positive references:
  `data/generated/historical_fire_weather_features_2023_2026.csv`
- Every clustered historical FIRMS candidate, regardless of official support:
  `data/generated/firms_israel_candidate_incidents_2023_2026.csv`
- Cached official settlement polygons and Fire and Rescue monthly aggregates,
  used only to preserve location/month context.

The official monthly aggregate is not used as the negative criterion. A sample
may remain valid even when its settlement/month has official wildfire activity,
because those records do not provide exact event timestamps or coordinates.

## Exclusion rule

Defaults are explicit and configurable:

- spatial exclusion radius: **5 km**
- temporal margin: **72 hours before incident start through 72 hours after
  incident end**

A proposed negative is rejected when a FIRMS candidate centroid is within 5 km
and its timestamp is inside `[candidate.start - 72h, candidate.end + 72h]`.
This uses the complete clustered incident duration and protects immediately
adjacent periods. Spatially close but safely time-separated samples and
temporally close but spatially distant samples are allowed.

The thresholds are more conservative than the historical clustering defaults
of 1.5 km linkage, 24-hour observation gap, and 72-hour maximum incident
duration.

## Sampling strategy

The default target is two negatives per supported positive. The builder does
not force a sample when no safe proposal is found after 250 attempts.

- The first proposal stream retains the exact positive centroid.
- The second uses a deterministic nearby point up to 10 km away.
- 80% of timestamp proposals prefer the same calendar month.
- Other proposals use nearby seasonal months.
- Hour-of-day is retained or shifted by at most one hour.
- Sampling spans only the temporal range represented by the FIRMS incidents.
- Seed `20260827` makes results reproducible.

Nearby points are remapped through the cached official polygons. If a point is
outside them, settlement fields stay empty; no settlement is inherited or
invented. This allows rural/open-area proxy negatives while keeping most
samples in the positive's surrounding geographic context.

Duplicate rounded coordinate/minute combinations are rejected. A local spatial
grid limits exclusion checks to relevant nearby FIRMS incidents instead of
performing an all-pairs scan. Nearest-candidate metadata is based on the
spatially nearest FIRMS candidate; its temporal value is the distance to that
candidate's full incident interval.

## Output and limitations

Output:

`data/generated/historical_fire_negative_samples_2023_2026.csv`

`official_month_support` is contextual only. It neither creates nor rejects a
negative label.

Important limitations:

- FIRMS non-observation is not proof of fire absence.
- Candidate centroids and exclusion radii simplify the true spatial footprint.
- Weather has deliberately not been collected for these samples yet.
- The strategy reduces geographic and seasonal bias but cannot eliminate it.
- Nearby displaced samples may represent different terrain or land cover.

Build deterministically:

```console
python -m scripts.build_historical_fire_negative_samples
```
