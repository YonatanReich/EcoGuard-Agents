# Air-pollution baseline lookup

Operational lookup is exact and active-only. Its complete identity is
`provider + station_id + channel_id + pollutant + canonical_unit +
baseline_family + month + hour`. Family is required and never defaulted or
substituted.

`AirPollutionBaselineLookupService.lookup()` selects only
`lifecycle_status = active`. The real-time detector explicitly requests
`baseline_family = five_minute_observation`; it never falls back to the
separate `completed_hour` family, whose imported versions remain draft. The
explicitly named draft-validation API is non-operational and must be invoked
deliberately.

The repository provides exact single and batch reads. Batch lookup uses one
session and a bounded set-based query while preserving input order, duplicates,
and the same availability semantics as individual lookup. Results distinguish:

- exact baseline available;
- insufficient history;
- profile or lifecycle-eligible version unavailable;
- missing month/hour bucket; and
- invalid or incompatible identity.

A missing row is not inferred to mean `NOT_MEASURED`. Available results include
statistics, sample/day/year counts, version ID and content hash, coverage and
lifecycle state, and stored schema/method/source/aggregation/quality provenance.

`AirPollutionLiveBaselineContextService` adapts normalized Ministry
`AirQualityObservation` values. Comparison requires the actual reading-supplied
unit, approved signed-value quality policy, exact identity, and the established
fixed `+02:00` provider-clock mapping. Raw readings request the five-minute
family; completed-hour consumers must explicitly request `completed_hour`.

The persisted-observation path reads source `air_pollution` rows from the
shared `observations` repository, deliberately maps only fields accepted by
`AirQualityObservation`, performs active batch lookup, and passes ordered
contexts to `AirPollutionAnomalyDetector`. Collector-envelope fields are not
blindly passed into the strict observation schema.
