# Resource allocator

The resource allocator is the final operational step of an emergency response:
it turns the Planner's recommended unit types into durable assignments of real
emergency stations.

The Planner decides **which services are required** (`fire_department`,
`police`, and `medical_services`). The allocator decides **which station of each
requested service should respond**. It does not decide how many vehicles or
internal teams a station should dispatch.

The current product policy assigns one station for every unique supported unit
type requested by the Planner. This policy also applies to earthquakes; an
earthquake does not obtain station quantities from the Planner response.

In the normal Coordinator flow the allocator runs only for emergency results.
Advisories do not reserve stations.

## Package structure

| File | Responsibility |
|---|---|
| `allocation_agent.py` | Public facade. Wires the services, builds allocation requests from Coordinator results, orders a batch, and attaches results back to incidents. |
| `request_preparation.py` | Validates and normalizes Fire, Flood, and Earthquake requests into the shared dictionary consumed by the executor. It also owns Flood target selection and deterministic Flood fallback plans. |
| `allocation_executor.py` | Executes one prepared request: settlement lookup, station selection, durable claim, route enrichment, shortages, and final result shaping. |
| `station_catalog.py` | Loads the Fire, Police, and MDA station catalogs once and builds their stable lookup keys. |
| `station_selection.py` | Produces ranked station candidates without writing allocations to the database. It handles police responsibility, availability filtering, road ranking, and straight-line fallback. |
| `station_allocation.py` | Owns durable station claims, release operations, active-allocation views, and enrichment of DB rows with station catalog data. |
| `allocation_routing.py` | Ranks candidates using route-matrix travel times and fetches full routes only for stations accepted by the database. |
| `flood_road_targets.py` | Turns hydrometric evidence into distinct, locally relevant, Mapbox-verified road response sites. |
| `mapbox_client.py` | Provider boundary for road verification, route matrices, and full directions. |
| `geo.py` | Shared coordinate validation and Haversine distance calculation. |

## End-to-end flow

```text
Coordinator emergency result
        |
        v
ResourceAllocationAgent.allocate_processing_results
        |
        +-- Fire: use the successful Planner response
        |
        +-- Earthquake: require a successful Planner response and apply the
        |                minimum-response allocation policy
        |
        +-- Flood: identify road targets, validate hydrometric risk, and adapt
                   the Planner response or build a deterministic fallback
        |
        v
AllocationRequestPreparer
        |
        v
Priority-sorted prepared request dictionaries
        |
        v
AllocationExecutor
        |
        +-- load settlement context
        +-- choose ranked candidates (no DB writes)
        +-- atomically claim stations in the DB
        +-- fetch full routes for claimed stations
        +-- attach actions, shortages, and routing status
        |
        v
Allocation result attached to the Coordinator result
```

## Prepared request contract

`AllocationRequestPreparer` returns ordinary dictionaries. A successful
prepared request contains the data needed by `AllocationExecutor`, including:

- `incident_id` and `hazard`;
- the validated `response_plan`;
- normalized `risk_score` and `risk_level`;
- UTC `queued_at` and `allocation_time` values;
- `urgency` and `effective_priority` for batch ordering;
- optional Earthquake policy metadata;
- an optional Flood `allocation_target`.

Failed or skipped Planner results are returned as terminal allocation results
and never reach station selection.

All hazards share the same queue key:

1. higher effective priority;
2. higher operational risk score;
3. more urgent response action;
4. earlier queue time;
5. incident id as a deterministic final tie-breaker.

Waiting adds one effective-priority point for every five minutes. No hazard is
given an unconditional advantage over another hazard.

## Station selection

Selection is deliberately separated from allocation. `StationSelectionService`
returns ranked candidate dictionaries but never persists an assignment.

For every requested unit type it:

1. loads the already cached catalog for that service;
2. validates coordinates and removes duplicate station identities;
3. ranks candidates by straight-line distance;
4. excludes Fire and MDA stations actively assigned to another incident;
5. asks the routing service for road travel time in bounded matrix batches;
6. ranks reachable candidates by travel time, road distance, and then
   straight-line distance.

If road ranking is unavailable, selection falls back to straight-line distance
and records the routing failure in the allocation result.

### Police responsibility

Police selection first tries to use the stations responsible for the town that
contains the event. If responsibility data is missing, the event is outside a
known town, or the responsible station is absent from the catalog, selection
falls back to the nearest normal police station and records the reason.

Police assignments represent area responsibility, so one police station may be
associated with several active incidents. Fire and MDA stations are exclusive
while their allocation is active.

## Durable allocation

`StationAllocationService` sends the ranked candidates to
`ResourceAllocationRepository.claim_stations`. The repository claims up to the
requested number atomically while holding the incident transaction lock.

The database claim is authoritative. The earlier availability filter avoids
unnecessary route requests, but it does not replace the atomic claim and cannot
by itself prevent concurrent allocations.

An allocation can later be released through `release_incident`. Release is
idempotent and records the release timestamp and reason. Active allocations can
be read back grouped by incident.

## Routing

Routing happens in two intentionally separate stages:

1. **Before the claim:** a Mapbox matrix ranks several candidate stations by
   travel duration and distance.
2. **After the claim:** full directions, geometry, Hebrew steps, and ETA are
   requested only for the stations the database actually accepted.

This avoids fetching expensive full routes for candidates that lose the DB
claim. If full directions fail after a successful claim, the station remains
allocated and receives an explicit unavailable route instead of losing the
durable assignment.

## Hazard-specific behavior

### Fire

Fire uses the successful Planner response directly after validating operational
risk and ensuring that every recommended unit has a valid response action.

### Earthquake

Earthquake allocation requires:

- a successful Earthquake Planner response;
- `earthquake_minimum_response_v1` as the allocation policy;
- a valid operational risk score and level.

The allocator assigns one station per supported recommended unit type and
persists the policy, basis, and quantity-source metadata. The prepared request
retains `hazard: "earthquake"`, so Coordinator results are matched by both
incident id and hazard like the other emergency types.

### Flood

Flood first needs a physical response destination. `FloodRoadTargetAgent`:

1. reads the latest valid hydrometric evidence for each station;
2. prefers road crossings of a matched stream;
3. otherwise searches a small station buffer, expanding only when necessary;
4. filters roads using class, vehicle-access, urban, and severity rules;
5. deduplicates representations of the same crossing using the shared
   Haversine calculation;
6. verifies each candidate against Mapbox before making it allocation-eligible.

The request preparer selects the highest-priority verified road site. One police
station is routed to the selected target unless a successful Planner response
requests a different supported set of unit types.

If there is no verified road site but valid hydrometric station coordinates are
available, the station becomes an explicitly marked fallback destination. Its
road route is retained, but the unresolved final field-access segment is marked
`partial_offroad` and requires field confirmation.

If the Planner is unavailable, validated Flood targeting and risk evidence can
produce a deterministic police fallback plan. If neither a verified site nor a
usable hydrometric location exists, Flood preparation returns a terminal skipped
result and does not attempt allocation.

## Result shape

The executor returns a dictionary containing, among other diagnostic fields:

- allocation `status` and `routing_status`;
- the requested, assigned, and shortfall count for each unit type;
- allocated stations grouped by service;
- unsupported Planner unit types;
- routing, catalog, responsibility, and persistence errors;
- settlement context for the event location;
- hazard-specific policy or target metadata when applicable.

Each allocated station includes its durable allocation identity, normalized
station data, selection reason, unit-specific response actions, and route.

A shortage or unsupported unit produces a partial result; it does not roll back
stations that were allocated successfully. Provider and enrichment failures are
reported explicitly rather than being treated as proof that no station was
allocated.

## Tests

Run the focused package tests with:

```powershell
.\venv\Scripts\python.exe -m pytest -q ecoguard/tests/resource_allocator
```

The suite covers request preparation, priority ordering, Fire/Flood/Earthquake
allocation, police responsibility, atomic-claim behavior, routing fallbacks,
Flood road targeting, release, and Mapbox response normalization.
