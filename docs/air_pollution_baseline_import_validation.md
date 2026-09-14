# Air-pollution baseline import validation

The validated `five_minute_observation` baseline cohort is imported and active
in the shared PostgreSQL baseline tables. It contains 388 active versions, one
per exact provider/station/channel/pollutant/unit/family profile. The separate
`completed_hour` cohort remains draft and is not used as a real-time fallback.

The five-minute cohort contains 111,744 month/hour buckets: 111,559 usable
(`ok`) buckets and 185 `insufficient_history` buckets. Coverage comprises 368
`FULL_BASELINE` and 20 `PARTIAL_BASELINE` profiles. Each version has exactly
288 month/hour rows. Activation retained profile, version, bucket, hash,
provenance, and coverage identity; it did not alter baseline statistics.

Operational lookup is active-only and requires the exact
`five_minute_observation` family. Draft lookup remains an explicitly named
validation path. There is no substitution across station, channel, pollutant,
unit, month/hour, or baseline family.

The historical cache and generated artifacts remain reproducibility inputs;
historical raw measurements are not backfilled into `observations`. Signed,
finite, provider-valid values are preserved under the documented versioned
quality policy. Baseline p95 remains statistical anomaly evidence, not a health
severity classification.

The import, activation, exact lookup, batch lookup, and persisted-observation
validation paths have been exercised against the shared database. Real database
validation confirmed that persisted Air Pollution observations can be adapted,
matched to active five-minute baselines, and evaluated by the detector.

This status does not imply a continuous detector consumer. Consumer scheduling,
cursor/checkpoint ownership, candidate persistence, and shared Coordinator /
Strainer handoff remain intentionally deferred to the shared architecture.
