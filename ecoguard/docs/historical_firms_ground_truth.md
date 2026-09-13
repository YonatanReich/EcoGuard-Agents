# Historical NASA FIRMS observations and candidate incidents

The historical builder uses only the official NASA FIRMS Area and Data
Availability APIs. It is separate from EcoGuard's production point-based
`FirmsDataAgent` and does not change live fire detection.

Run it from the repository root:

```console
python -m ecoguard.scripts.build_historical_firms_dataset \
  --start 2023-01-01 --end 2026-08-27
```

The date range is configurable. The two generated CSV files under
`data/generated/` are ignored by Git.

## Progress, retries, and resume

Every successful five-day request window is normalized and atomically saved
under `data/generated/firms_history_checkpoint/windows/`. A versioned
`manifest.json` binds those files to the requested date range, bounds, product
plan, API window size, and clustering parameters. On restart, compatible and
checksum-valid windows are loaded from disk and not downloaded again.

When every planned window is already present, the builder validates the
manifest and every window checksum locally before downloading product
availability. It can therefore proceed directly to clustering with no NASA
request. A partial checkpoint still refreshes official availability before
requesting only its missing windows.

A corrupt manifest/window or incompatible configuration stops the build
clearly rather than mixing data. Use a different `--checkpoint-dir` for a
different configuration. Final raw and candidate CSVs remain atomic and are
written only after every window is available.

Progress is printed after every downloaded or resumed window:

```text
Progress: 312 / 798 requests (39.1%)
Product: VIIRS_NOAA20_SP
Window: 2024-07-11 -> 2024-07-15
Hotspots collected: 4823
Elapsed: 00:41:22
Source: download
```

Provider timeouts, network errors, HTTP 408/425/429, and HTTP 5xx responses
receive at most four total attempts with bounded exponential delays of 2, 4,
and 8 seconds. Authentication errors and other permanent HTTP failures stop
immediately. Retry output contains only a safe reason, product, and date
window—never the credential-bearing URL or MAP key.

Before any Area API download, the generated SP/NRT plan is validated against
the current official availability response. Per-satellite windows must remain
inside their advertised product ranges and must contain neither overlaps nor
gaps. An HTTP 400 response whose safe provider message is `Invalid MAP_KEY` is
classified as an authentication error, not mistaken for a date-boundary error.

## Products

The builder queries FIRMS availability at runtime. It prioritizes the
science-quality standard-processing products `VIIRS_SNPP_SP` and
`VIIRS_NOAA20_SP`. Because standard processing has a publication lag, the
corresponding NRT products fill only later, non-overlapping dates. NOAA-21 is
represented by `VIIRS_NOAA21_NRT`, since the FIRMS API currently does not list
a NOAA-21 standard-processing source. Every observation retains its satellite
and exact source-product metadata.

## Geographic scope

Requests use the conservative rectangle `34.2,29.4,35.9,33.4`. A rectangle is
not proof that every observation is inside Israel, and it is not represented as
a political boundary. No invented boundary polygon is used. Matching with more
precise authoritative geography can be a separate validation step.

## Hotspots and clustering

A FIRMS hotspot is a satellite thermal-anomaly observation, not a confirmed
wildfire or one independent incident. Raw observations therefore remain in a
separate file from clustered candidate incidents.

The explainable initial clustering defaults are:

- maximum centroid distance: **1.5 km**;
- maximum gap from the cluster's latest observation: **24 hours**;
- maximum total candidate duration: **72 hours**.

Observations are processed chronologically. An observation joins the nearest
eligible cluster only when all three limits are satisfied. The duration cap
handles persistent multi-day fires explicitly: continued detections after 72
hours begin another candidate instead of allowing an unlimited chain to merge
many days into one incident. All parameters are command-line configurable.

Clustering keeps only temporally eligible clusters in an expiry heap and
indexes their centroids in a small geographic grid. Grid lookup only produces
possible neighbors; exact Haversine distance and the original deterministic
nearest-cluster tie-breaker still decide membership. Timestamps and incremental
centroid sums are cached instead of being reparsed or rescanned in the inner
loop. This avoids comparing each observation with every historical cluster.

## Limitations

- Thermal anomalies can represent non-wildfire heat sources.
- Cloud, smoke, satellite orbit timing, and sensor sensitivity can hide fires.
- The rectangular query includes some neighboring territory and water.
- Clusters are candidates, not official incident labels.
- Standard and NRT product availability changes over time.

Clustering is necessary before comparison with the Fire and Rescue aggregate
statistics because multiple satellite observations can refer to one continuing
fire. Even after clustering, the official monthly settlement totals cannot be
treated as one-to-one matches because they lack exact incident timestamps and
coordinates.
