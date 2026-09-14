# Air-pollution operational compatibility

## Live collection and persistence

`AirPollutionCollector` is registered in the shared scheduler at a five-minute
cadence. It uses `MinistryAirQualityClient`, `BaseCollector`, the shared
`ObservationRepository`, and `collector_runs`; no Air Pollution-specific
scheduler or persistence layer exists. Normalized measurements are written to
the shared `observations` table, with station/channel/pollutant identity,
reading and metadata unit provenance, provider timestamp, coordinates, and
provider validity/status evidence. Shared observation identity provides
first-seen idempotency.

Live unit provenance distinguishes `reading`, `metadata_fallback`, and
`unknown`. Only a reading-supplied unit qualifies for baseline comparison.
`ecoguard-provider-valid-signed-v1` accepts finite signed values when the
provider explicitly marks them valid, while rejecting missing, malformed,
non-finite, sentinel, and provider-invalid values. This is an EcoGuard policy,
not a claim of Ministry scientific acceptance.

## Clock and comparison compatibility

Stored UTC timestamps are mapped to the provider's documented fixed `+02:00`
clock, preserving the established `timeBeginning=false` label semantics. The
real-time baseline pools provider five-minute observations by month/hour; it is
not a completed-hour average and does not require waiting for hour completion.
The separate completed-hour family remains unchanged and draft.

Operational exact and batch lookup use only active
`five_minute_observation` versions. The detector rule remains:

- live value above p95: `SUSPECTED_ANOMALY`;
- live value at or below p95: `NORMAL`;
- unsafe or unavailable comparison: `NOT_EVALUATED`.

p95 is anomaly evidence only; it does not determine health severity, confidence,
emergency status, or response priority.

## Persisted observation processing

The current validation path is:

```text
shared observations
  -> explicit AirQualityObservation adapter
  -> active five_minute_observation batch lookup
  -> AirPollutionAnomalyDetector
  -> ordered NORMAL / SUSPECTED_ANOMALY / NOT_EVALUATED results
```

The read repository is bounded, source-scoped, ordered by ingestion boundary,
and read-only. The adapter ignores collector-envelope fields rather than
passing the full payload into strict schema validation. Real database validation
of this path succeeded.

This is not yet a continuously scheduled observation consumer. A shared owner
for scheduling, cursor/checkpoint semantics, retries, and candidate persistence
has intentionally not been introduced. The shared Coordinator / Strainer is not
implemented in the current architecture, so automatic downstream handoff also
remains deferred. Air Pollution must ultimately route `NON_EMERGENCY` and must
never enter the Emergency Analyzer.

Trend ML and frontend/shared-incident integration remain future work. Existing
Air Pollution Analyzer, population/spatial evidence, and protocol-grounded
non-emergency planning components do not change those deferred shared-runtime
boundaries.
