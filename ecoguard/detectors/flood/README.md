# Flood detector

The active detector is deliberately limited to official hydrometric discharge
thresholds. No inferred or environmental context participates in its decision.

## Components

- `worker.py` reads new hydrometric observations and commits lifecycle changes
  together with cursor advances.
- `detection_agent.py` rejects stale or implausibly future observations and
  suppresses duplicate openings for active events.
- `station_rules.py` contains the active deterministic threshold, persistence
  and hysteresis rules.

## Eligible observations

The station catalog classifies each Q2-Q100 vector as
`complete_thresholds`, `missing_thresholds` or `partial_thresholds`. Only
`complete_thresholds` stations are copied from the raw hydrometric source table
to the shared `observations` stream. The active rules validate the status and
the complete, positive, strictly increasing vector again at the decision
boundary.

Stations whose provider vector is six `999` sentinels remain available in the
catalog and raw source observations for audit. They produce no detector signal.

## Severity

Current discharge is compared with all six official thresholds:

| Level | Discharge |
|---:|---|
| 0 | below Q2 |
| 1 | Q2 to below Q5 |
| 2 | Q5 to below Q10 |
| 3 | Q10 to below Q20 |
| 4 | Q20 to below Q50 |
| 5 | Q50 to below Q100 |
| 6 | Q100 or higher |

The operational interpretation is:

| Level | State |
|---:|---|
| 0-1 | `none` — ordinary flow, including Q2 |
| 2 | `monitoring` — Q5 preliminary monitoring |
| 3 | `active` — Q10 flood alert |
| 4 | `severe` — Q20 severe alert |
| 5-6 | `emergency` — Q50/Q100 emergency alert |

Q5 is a monitoring state only. A flood event begins at level 3 (Q10).

## Persistence and lifecycle

An alert opens only when the two latest valid readings are both at or above
Q10. Severity is the level of the current reading; the previous reading confirms
that the station was already above the alert threshold. Consecutive readings
may be at most 30 minutes apart. Missing discharge, an ineligible threshold
status or an invalid vector breaks the sequence.

An active alert resolves only after two consecutive valid readings are both
strictly below 80% of Q10. The same 30-minute maximum gap applies. Missing or
stale readings never resolve an event.

Each station has one stable active event key. Candidate inserts, resolutions
and detector cursor advances commit in one transaction; a failed evaluation
advances no cursor.

## Compact result

Every newly opened alert includes these primary fields:

```text
station_id
stream_id
timestamp
current_discharge
severity_level
alert_level
```

`stream_id` is the internal `streams.id` value when the materialized topology
contains a confirmed station-to-stream match; otherwise it is `null`. It is
output enrichment only and does not affect threshold evaluation.

Lifecycle identity, location, the complete threshold vector, the two confirming
discharges, the current threshold and its return period remain available as
supporting evidence.

## Entry point

`run_flood_detector()` performs one timer-safe detector tick. It reads only
`water_authority_hydrometric_observations`; rain-gauge and radar collectors may
still cache source data for other uses but are not flood-detector inputs.
