# FIRMS–Fire and Rescue ground-truth matching

This stage maps historical FIRMS candidate centroids to official settlement
polygons and compares them with monthly Israel Fire and Rescue aggregates. It
does not train a model and does not modify production detection.

## Official settlement source

Settlement boundaries are downloaded from the official Knesset Research and
Information Center ArcGIS organization, layer `muni_vaadim`. This service
publishes the Ministry of Interior statutory-boundary layer. The layer contains
municipality and local-committee polygons, Hebrew names, and LAMAS codes.
GeoJSON is downloaded in WGS84, validated, and cached locally at:

`data/generated/israel_settlement_boundaries.geojson`

The provenance manifest records the service URL, download time, feature count,
and SHA-256 hash. Both generated files are ignored by Git. Refresh explicitly:

```console
python -m scripts.build_firms_fire_rescue_ground_truth --refresh-boundaries
```

Subsequent runs use the local cache and make no per-candidate geocoding calls.

## Settlement mapping

Polygon bounding boxes are inserted into a 0.1-degree grid. A FIRMS centroid
queries only its grid cell, followed by exact local point-in-polygon testing.
Polygon holes and multipolygons are supported. If overlapping official
polygons contain a point, a local-committee polygon is preferred over its
regional municipality; remaining ties use polygon area, LAMAS code, and name.

Points outside all official polygons receive no invented settlement or code
and use `settlement_match_status=outside_official_settlement_polygon`.

## Official monthly matching

Relevant official scenarios are strictly:

- שריפת צמחייה באינדקס רגיל
- שריפת צמחייה באינדקס גבוה / קיצון
- שריפת יער

Waste fires and unattended bonfires are excluded. Matching uses the FIRMS
candidate start year/month and normalized settlement LAMAS code. All relevant
official scenario counts for that key are summed, while scenario names remain
visible in `official_scenarios`.

## Aggregation limitation and support categories

The Fire and Rescue records are monthly aggregates. A match means only that
relevant fires were officially recorded in the same settlement and month. It
does **not** confirm that an individual FIRMS candidate corresponds to an
individual official incident. The full monthly `official_event_count` may
therefore appear on more than one FIRMS candidate and is never distributed or
decremented between candidates.

- `official_month_support=true` means only that a relevant official aggregate
  exists for the candidate's settlement and calendar month.
- `firms_candidates_same_settlement_month` reports how many FIRMS candidates
  share that same settlement/month key, making any many-to-one ambiguity
  explicit.
- `supported`: mapped to a settlement with a relevant official monthly
  aggregate.
- `unsupported`: mapped to a settlement, but no relevant official monthly
  aggregate exists.
- `unlocated`: outside all cached official settlement polygons.

These are deterministic support labels, not probability scores or individual
fire confirmations. `unsupported` and `unlocated` are unknown/unverified cases;
they must not be used as negative or no-fire samples.
