# Air-pollution baseline persistence

Migrations 0009 and 0010 add the compact Air Pollution baseline persistence
layer without replacing the shared `observations` or `collector_runs` tables.
The four baseline tables are:

- `air_pollution_station_catalog`;
- `air_pollution_baseline_profiles`;
- `air_pollution_baseline_versions`; and
- `air_pollution_baseline_buckets`.

Profile identity is provider/station/channel/pollutant/canonical unit plus
`baseline_family`. Allowed families are `completed_hour` and
`five_minute_observation`. Version rows hold immutable content hashes and
scientific provenance independently from lifecycle state. Bucket rows hold one
month/hour profile with counts, years, status, and signed distribution
statistics. No constraint assumes concentrations are nonnegative.

The partial unique index
`air_pollution_baseline_versions_one_active` permits at most one active version
per profile. Because family is part of profile identity, each family has an
independent lifecycle. The guarded activation workflow validates and locks an
entire target cohort in one serializable transaction, supersedes an old active
version when present, activates the selected draft, verifies the final
one-active invariant, and rolls back atomically on failure.

Current verified state:

- `five_minute_observation`: 388 active versions, 368 full and 20 partial,
  containing 111,744 buckets;
- `completed_hour`: separate imported versions remaining draft.

The import CLIs default to dry-run. Writes require both `--write` and
`--confirm-write`; activation uses the same guarded posture. Import plans
verify artifact checksums, reject malformed or conflicting content, preserve
nullable historical `generated_at` when absent, and insert only compact
profiles and buckets. They never regenerate artifacts or load raw historical
readings into the operational observation history.

Operational services consume only active versions. No baseline import or
activation is performed automatically by collection, detection, or application
startup.
