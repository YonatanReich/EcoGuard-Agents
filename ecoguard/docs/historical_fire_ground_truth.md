# Historical Israeli Fire and Rescue ground truth

The generated dataset comes only from the official **Israel Fire and Rescue**
“אירועים לפי מחוז” dataset published through data.gov.il. The builder discovers
the package's active CSV resources through the official CKAN API and selects
resources for 2023–2026. It prefers the CKAN DataStore API when available and
otherwise downloads the official CSV resource.

Run the builder from the repository root:

```console
python -m ecoguard.scripts.build_historical_fire_ground_truth
```

The generated file is
`data/generated/israel_fire_rescue_open_area_2023_2026.csv` and is ignored by
Git.

## What a row means

Each row is one normalized **aggregate** reported by the official source for a
year, month, district, event domain/type, scenario, and settlement. The
`event_count` is preserved as a count. For example, an official row with
`event_count = 7` remains one row; it is not expanded into seven invented fire
events.

The first dataset keeps only the fire domain and open-area event type. The
original scenario wording is retained so vegetation and other open-area
scenarios can be examined later.

## Limitations

These statistics do not provide an exact timestamp or latitude/longitude for
each incident represented by an aggregate. The builder does not invent those
values, so this dataset cannot by itself identify an individual fire's precise
time or coordinates.

In a later, separate validation stage, the monthly/settlement aggregates can be
compared with NASA FIRMS observations at a compatible geographic and temporal
level. They must not be treated as one-to-one incident matches without more
precise official evidence.
