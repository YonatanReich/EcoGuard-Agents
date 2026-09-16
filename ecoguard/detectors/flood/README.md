# Flood detector

The current implementation is split into three small parts:

- `worker.py` owns database reads, cursor handling and the success transaction.
- `detection_agent.py` exposes the flood-specific `evaluate()` interface.
- `rules.py` contains deterministic, side-effect-free threshold rules.

## Data flow

1. Flood collectors cache source data in PostgreSQL. Water Authority readings
   keep their detailed source tables and are also normalized into the shared
   `observations` stream. IMS PPI HDF5 frames are converted from numeric `RATE`
   pixels to 5 km cell observations and cached in `observations`.
2. The worker reads `detector_cursors` and fetches only newly ingested rows.
   Delayed backfills and implausible future timestamps advance the cursor but
   cannot open or resolve a real-time event.
3. For affected cells it reloads at least 24 hours of observations and joins
   the precomputed `flood_cell_context`, monthly station baselines and
   basin-wide rain window. Gauge events also join the materialized
   station-to-stream match and complete downstream route.
4. `FloodDetectionAgent.evaluate()` applies transparent threshold-crossing
   rules. It covers gauged rivers, rain-only natural catchments and short
   intense urban rain.
5. Candidate inserts and cursor updates share one transaction. A failed run
   advances no cursor; a run with no new observations performs no writes.

## Event lifecycle

Each candidate has an internal stable `event_key`. A threshold crossing opens
one active row in `flood_candidates`; repeated high readings do not open more
rows for that event. Source-specific exit rules use 80% of the opening
threshold to avoid rapid open/close changes around the boundary.

Gauge events use two consecutive readings from the same station and metric.
Natural rain events use two consecutive rainfall frames and also check basin
support. Urban rain events remain active for at least one hour and resolve only
after a continuous 30-minute low-rain period, with no observation gap longer
than 15 minutes. The radar collector therefore retains otherwise-dry frames
for cells with an active rain event. Missing or stale data never resolves an
event.

Opening candidates and resolutions are persisted with cursor advances in the
same transaction. The worker returns newly committed candidates separately
from `resolutions`; it does not delete historical events.

No detector code fetches an external service. Scheduling also remains outside
this package.

Radar rows participate only when at least half of their mapped pixels are
valid. Basin rainfall is the area-normalized accumulation across all 5 km cells
in the basin; sparse, absent radar cells count as dry. It can increase
confidence in a natural-flood candidate and prevent premature resolution, but
it cannot open an event without a local threshold crossing.

## One-time/static preparation

After migrations and the existing hydrology/surface loaders have been applied,
run `python -m ecoguard.scripts.load_hydrology_static_data`. It materializes
station-to-cell links, basin/terrain/urban/stream context, and per-station
monthly baselines. It also matches each hydrometric station to a stream once
and follows the Water Authority's declared downstream ids to the end of the
known graph. Re-run it only after static layers change or after enough new
history has accumulated to refresh baselines.

The same command caches the official historical-station registry from
data.gov.il. Hydrograph station numbers are mapped to live-endpoint station ids
once using WGS84 distance and normalized Hebrew/English names. Automatic links
are limited to 100 m by coordinates alone, or 500 m when name similarity is at
least 0.72. The mapping keeps distance, similarity, confidence and review state;
reviewed links are never overwritten by a later automatic refresh.

Historical hydrograph CSV exports are loaded separately and explicitly:

```text
python -m ecoguard.scripts.import_historical_hydrographs <file.csv> [file.csv ...]
```

The importer expects the Water Authority's CP1255 export format. It validates
the complete file before writing, identifies unchanged content by SHA-256 and
replaces a changed file atomically. Source rows are cached in
`historical_hydrometric_observations`, never in the real-time `observations`
stream, so a historical import cannot advance a detector cursor or emit an
event. Rows marked as sewage remain available for audit but are excluded from
baseline calculations. Repeated segment-boundary timestamps are collapsed
before statistics are calculated. Historical water elevation is retained but
is not mixed into the live stage baseline until both sources' vertical datum is
verified; the historical files currently strengthen discharge baselines only.

Urban cover is sampled at nine fixed points per 5 km operational cell and
stored as `built_up_fraction`, `is_urban` and a classification status. At least
five valid WorldCover samples are required; missing coverage remains `unknown`
instead of silently becoming natural terrain. Hydrometric and rain stations are
also assigned directly to drainage basins during this same static refresh.

A monthly baseline combines mapped historical hydrographs with sufficiently old
live readings. It is eligible only after the station cache covers all twelve
months and at least 330 days. The selected metric also needs 300 valid samples
across ten distinct days in that month. The newest seven days of live readings
are excluded so an active flood cannot raise its own baseline. Until those
conditions are met, official Q2-Q100 rating thresholds remain the primary
station rule.
The lowest available official return-period threshold opens an event, while the
highest Q2, Q5, Q10, Q20, Q50 or Q100 threshold exceeded determines the
severity evidence. A discharge p95 baseline is used only when that station has
no usable official return-period threshold.

## Entry points

- `RadarPPICollector().run()` caches recent numeric radar cells.
- `load_hydrometric_observations()` caches hydrometric readings.
- `load_rainfall_observations()` caches rain-gauge readings.
- `run_flood_detector()` performs one timer-safe detector tick and returns
  `no_op`, processed counts, newly inserted candidates and newly committed
  event resolutions. The full field-by-field response is defined in
  [`../../docs/api_contract.md`](../../docs/api_contract.md), section 6.

Each opening candidate exposes the complete detector result. In addition to
identity, confidence and severity, it includes `is_urban`, the trigger,
machine-readable reasoning, hydrological and rainfall evidence, station and
basin metadata, stream matching and the full known downstream route. The
worker returns this object unchanged after its database transaction commits.

The `location` object always states its source. Gauge events use the station
coordinate. Rain events use the strongest contributing rain-gauge location or
the maximum-rate radar pixel when available, otherwise the 5 km cell center.
For rain-only events this is the best observed rain coordinate, not proof of
standing water; `location_uncertainty_m` preserves that distinction for later
resource allocation.

## Radar authentication

The IMS radar directory uses NTLM challenge-response authentication. Configure
`IMS_RADAR_USERNAME` and `IMS_RADAR_PASSWORD` in the runtime environment; use
the same username/domain format accepted by the IMS browser login. Do not store
these values in source code or in the database. `IMS_RADAR_COOKIE` is supported
for provider compatibility but is optional: the collector has been verified
against IMS using NTLM alone.

An authentication failure is recorded as a failed collector run and never
advances a detector cursor. Repeated frames are safe: observation identity and
upsert logic make an immediate second collector run write zero duplicate rows.
On an empty cache the collector starts with the newest six frames. Later runs
read the last cached provider frame from `radar_frame_cache`, fetch every newer
frame advertised by IMS, and re-fetch two older frames as a safe overlap. Frame
watermarks and cell observations commit together, including completely dry
frames, so a long collector outage can be filled without silently skipping
provider data.

The current implementation uses cached elevation, slope, basin, stream distance
and urban classification. It intentionally does not yet model DEM flow
direction or GovMap floodplain polygons. Radar decisions use accumulated mean
rainfall over each 5 km cell; an isolated high-intensity pixel is retained as
evidence but cannot open an event by itself.

For a deployment with several collector processes, use a direct PostgreSQL
endpoint. Transaction-pooler connections cannot guarantee the session-level
single-flight advisory lock used by collectors.
