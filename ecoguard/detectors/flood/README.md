# Flood detector

The flood detector follows the same runtime flow and output contract as the
other EcoGuard detectors:

```text
collector -> observations -> detect_new() -> list[CellSignal] -> Coordinator
```

The shared `incidents` table is the only event lifecycle store. There is no
Flood-specific worker, cursor table, candidate table or scheduler job.

## Collection and eligibility

The Water Authority collector runs every ten minutes, matching the provider's
publication cadence. It keeps every provider reading in the raw hydrometric
source table, but copies readings into the shared `observations` stream only
for stations classified as `complete_thresholds`.

Stations whose threshold vector is six `999` sentinels are classified as
`missing_thresholds`. Beyond the catalog and raw source table, the live system
does no work for those stations: it stores no shared observation and therefore
cannot evaluate them or open an incident.

## Severity and alert threshold

Discharge is compared with the official Q2, Q5, Q10, Q20, Q50 and Q100 values:

| Severity | Discharge | Operational state |
|---:|---|---|
| 0 | below Q2 | none |
| 1 | Q2 to below Q5 | none |
| 2 | Q5 to below Q10 | monitoring only |
| 3 | Q10 to below Q20 | active alert |
| 4 | Q20 to below Q50 | severe alert |
| 5 | Q50 to below Q100 | emergency |
| 6 | Q100 or higher | emergency |

Q10 is the first level allowed to emit a flood signal. Two valid consecutive
readings at or above Q10, no more than 30 minutes apart, are required. Every
later qualifying pair emits another ordinary `CellSignal` and keeps the shared
incident active.

Each signal includes `station_id`, optional `stream_id`, timestamp, current
discharge, severity, alert level, the threshold vector and the two readings
used in the decision.

## Scheduling and event closure

Flood detection runs in the same shared thirty-minute detection batch as Fire
and Air Pollution. It uses the same successful-run bookmark pattern as the
other detectors and returns a plain `list[CellSignal]`.

The Coordinator applies its existing quiet-period lifecycle rule. A Flood
incident closes after three hours without a new qualifying signal. A later
confirmed Q10 pair creates a new incident. Closed incidents remain stored in
`incidents`; they are not physically deleted.

## Current downstream boundary

Flood incidents are persisted and routed to the emergency queue. There is not
yet a Flood analyzer, response planner or frontend event projector, so dispatch
currently reports the Flood route as unsupported after the incident itself has
already been stored successfully.
