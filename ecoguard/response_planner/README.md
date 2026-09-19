# response_planner/

Turns an assessment into a plan: which units do what, by when, grounded in
published protocol rather than invented.

## Shared emergency planner

`emergency/EmergencyResponsePlanner` is the common planning boundary for Fire
and Flood. Its analyzer-agnostic required handoff is only `hazard_type` plus a
non-empty `event_description`. Incident identity, location, risk context,
evidence gaps, limitations and analyzer-specific context are optional trusted
context. The planner preserves supplied context but does not derive missing
risk, population, spread or inundation, select facilities or vehicles,
calculate resource quantities, or claim dispatch.

Analyzer-specific integration belongs outside the shared planner:

```text
Fire Analyzer  -> fire  + textual event description -> EmergencyResponsePlanner
Flood Analyzer -> flood + textual event description -> EmergencyResponsePlanner
Future analyzer -> supported hazard + description   -> the same planner
```

The integration adapter decides how to summarize analyzer fields into the
description. The shared planner neither imports nor interprets an analyzer's
schema.

- **Fire:** supported through the existing `fire/ResponsePlanningAgent`
  compatibility wrapper. Its adapter converts current Fire analysis fields
  into the generic textual description and optional context.
- **Flood:** the shared planner routes to the approved Flood corpus and can plan
  directly from a Flood event description. No Flood Analyzer, coordinator, or
  runtime integration is included here.

Protocol retrieval is isolated by hazard. Neither hazard falls back to the
other's doctrine.

`protocols/` is the RAG corpus, one directory per hazard, each with a manifest
carrying per-document sha256 and licence. It lives here rather than under
`data/` because the corpus and the agent citing it are one thing — a protocol
added without a planner change is invisible, and a planner change without the
corpus is ungrounded.

Retrieval itself is in `ecoguard/shared/protocols.py`, because analysis and the
plan judge read the corpus too.
