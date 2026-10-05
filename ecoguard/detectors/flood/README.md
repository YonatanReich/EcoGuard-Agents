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
publication cadence. It writes directly to the shared `observations` stream
and includes only active stations that have `complete_thresholds` and a
reviewed `operational_flow_regime`.

The regime is loaded into the station table from the reviewed
`hydrometric_station_flow_regimes.csv` reference; station ids are not embedded
in detector or collector code.

Stations whose threshold vector is six `999` sentinels are classified as
`missing_thresholds`. They remain in the station catalog, but their measurements
are not stored, evaluated or allowed to open an incident.

## Detection and operational severity

Detection uses two consecutive readings no more than 30 minutes apart:

- `ephemeral`: both readings must be at least 1 m3/s.
- `flowing_baseline`: both readings must be at least the station's Q2.

The detector still compares the current discharge with Q2, Q5, Q10, Q20, Q50
and Q100. The actual return period is retained in evidence, while confirmed
events map onto the existing operational severity contract:

| Severity | Confirmed discharge band |
|---:|---|
| 3 | below Q5, including an ephemeral event below Q2 |
| 4 | Q5 to below Q10 |
| 5 | Q10 to below Q20 |
| 6 | Q20 or higher |

Every later qualifying pair emits another ordinary `CellSignal` and keeps the
shared incident active. The history query loads one hour; only a reading no
more than 30 minutes before the new target can confirm it.

Each signal includes `station_id`, optional `stream_id`, timestamp, current
discharge, flow regime, detection threshold, actual return period, operational
severity, alert level, the threshold vector and the two readings used in the
decision.

## Scheduling and event closure

Flood detection runs in the same shared ten-minute detection batch as Fire
and Air Pollution. It uses the same successful-run bookmark pattern as the
other detectors and returns a plain `list[CellSignal]`.

The Coordinator applies its existing quiet-period lifecycle rule. A Flood
incident closes after three hours without a new qualifying signal. A later
confirmed pair creates a new incident. Closed incidents remain stored in
`incidents`; they are not physically deleted.

## Current downstream boundary

Flood incidents are persisted and routed to the emergency queue. Event and
risk analyzers interpret the detector evidence, and the shared emergency
planner produces the response plan. Resource allocation keeps its existing
road-targeting stage and its existing police fallback when planning is
unavailable. Road proximity affects only the response destination, never flood
detection. Flood also remains subject to the shared dispatcher freshness gate.
