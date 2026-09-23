# Resource allocator

The last step: which actual stations respond.

The planner says "two fire crews and an ambulance". The allocator picks *which*
ones, by road travel time rather than straight-line distance, and reserves them
against the incident so the same crew is not promised to two fires at once.

It only runs for emergencies. An advisory never reserves anyone.

## What is here

| File | What it does |
|---|---|
| `allocation_agent.py` | Matches required unit types to real stations and commits the reservation |
| `allocation_routing.py` | Ranks station candidates by road travel and attaches full routes after reservation |
| `geo.py` | Provides shared geographic distance calculations |
| `flood_road_targets.py` | Works out which road sites a flood response needs to cover |

## Things worth knowing

Reservations are claimed atomically in the database, so two processes cannot
allocate the same station twice.

When a station is released - the incident closed, or the plan changed - it
becomes available again with a recorded reason.
