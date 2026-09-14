# Ministry Air Pollution collection

Phase 1 reuses the Ministry/Envista guest client and its offline regression
tests from `EA-329-air-pollution-analyzer-contract`. Measurement primitives
were extracted into `services/air_quality_schemas.py` so collection has no
dependency on anomaly, event, or analyzer schemas.

`AirPollutionCollector.fetch()` returns normalized readings to the existing
`BaseCollector.run()`, observation repository, and `collector_runs` audit.
No new table, migration, background thread, or downstream processing is used.
The shared scheduler polls every five minutes, preserving the previous
runtime's interval. The provider's latest endpoint is queried with its existing
four-hour lookback; this is polling latest values, not a history backfill.
Guest tokens/cookies are obtained automatically and never persisted.

## Observation mapping

- `source`: `air_pollution`.
- `cell_id`: `ministry:<station>:<channel>:<pollutant>:<unit>`; each component
  is URL-escaped. This is a source-local station series identity, not a grid
  assignment (Telegram already uses source-local message identities).
- `location`: station WGS84 coordinates, stored by the shared repository as
  `geography(Point,4326)`.
- `observed_at`: the provider timestamp converted to UTC using its explicit
  offset. Naive/malformed timestamps are rejected. Future values are excluded
  against both collection time and the collector clock; no timezone is guessed.
- `payload`: normalized concentration and unit, original unit, station/channel/
  pollutant IDs, coordinates, original timestamp text, provider identity,
  status ID/name, `valid=true`, `preliminary_unvalidated` quality, collection
  timestamp and collection status.

Invalid/sentinel/nonfinite readings, inactive stations/channels and unsupported
variables/units are excluded by the adapter. Provider valid=true is authoritative
for the versioned signed ingestion policy; status is preserved as evidence, not
an independent name-based rejection. A reading remains preliminary, not certified.
The existing adapter permits valid readings when status metadata is unavailable;
the payload records partial collection and missing status where applicable.
Logs report exclusion/future/error counts without raw provider errors or secrets.

The existing `(source, cell_id, observed_at)` constraint ignores repeat readings.
As elsewhere in the shared store, later provider corrections to that identity
do not overwrite the first stored reading. A partial collection stores its
usable readings and logs counts; the shared audit marks a successful write
`ok`, while payload `collection_status` retains provider partial status. Failed
collections raise a sanitized error for the shared failed-run audit.

## Operational compatibility update

Signed provider-valid readings now carry explicit unit and quality provenance.
See [the approved compatibility contract](air_pollution_operational_compatibility.md)
for unknown-unit handling, fixed provider clock and offline completed-hour
aggregation. No database or scheduler change accompanies this layer.
