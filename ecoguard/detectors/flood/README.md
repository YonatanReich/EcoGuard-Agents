# Flood detector

The current implementation is split into three small parts:

- `worker.py` owns database reads, cursor handling and the success transaction.
- `detection_agent.py` exposes the flood-specific `evaluate()` interface.
- `rules.py` contains deterministic, side-effect-free threshold rules.

The older station-centric implementation is kept temporarily in
`legacy_detection_agent.py`; neither the new worker nor the collectors call it.

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
   basin-wide rain window.
4. `FloodDetectionAgent.evaluate()` applies transparent threshold-crossing
   rules. It covers gauged rivers, rain-only natural catchments and short
   intense urban rain.
5. Candidate inserts and cursor updates share one transaction. A failed run
   advances no cursor; a run with no new observations performs no writes.

## Event lifecycle

Each candidate has an internal stable `event_key`. A threshold crossing opens
one active row in `flood_candidates`; repeated high readings do not open more
rows for that event. The worker resolves the row only after two fresh readings
are both below 80% of the opening threshold. This lower exit threshold avoids
rapid open/close changes around the boundary.

Gauge events use two consecutive readings from the same station and metric.
Rain events use two consecutive rainfall frames for the same cell and require
all applicable rolling accumulations to be below their exit thresholds. The
radar collector therefore retains otherwise-dry frames only for cells with an
active rain event. Missing or stale data never resolves an event.

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
monthly baselines. Re-run it only after static layers change or after enough new
history has accumulated to refresh baselines.

The same command caches the official historical-station registry from
data.gov.il. Hydrograph station numbers are mapped to live-endpoint station ids
once using WGS84 distance and normalized Hebrew/English names. Automatic links
are limited to 100 m by coordinates alone, or 500 m when name similarity is at
least 0.72. The mapping keeps distance, similarity, confidence and review state;
reviewed links are never overwritten by a later automatic refresh.

Urban cover is sampled at nine fixed points per 5 km operational cell and
stored as `built_up_fraction`, `is_urban` and a classification status. At least
five valid WorldCover samples are required; missing coverage remains `unknown`
instead of silently becoming natural terrain. Hydrometric and rain stations are
also assigned directly to drainage basins during this same static refresh.

A monthly baseline is eligible only after the station cache covers all twelve
months and at least 330 days. The selected metric also needs 300 valid samples
across ten distinct days in that month. The newest seven days are excluded so
an active flood cannot raise its own baseline. Until those conditions are met,
official Q2-Q100 rating thresholds remain the primary station rule.
The lowest available official return-period threshold opens an event, while the
highest Q2, Q5, Q10, Q20, Q50 or Q100 threshold exceeded determines the
severity evidence.

## Entry points

- `RadarPPICollector().run()` caches recent numeric radar cells.
- `load_hydrometric_observations()` caches hydrometric readings.
- `load_rainfall_observations()` caches rain-gauge readings.
- `run_flood_detector()` performs one timer-safe detector tick and returns
  `no_op`, processed counts, and newly inserted candidates.

Each opening candidate intentionally exposes only identity/location plus
`confidence`, `severity_hint`, and `location_uncertainty_m`. Detailed opening
and resolution evidence remains in `flood_candidates` for audit and tuning.
