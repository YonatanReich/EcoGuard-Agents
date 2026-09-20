# resource_allocator/

Decides which actual stations answer a response plan. Available stations are
ranked by Mapbox road travel time, with straight-line distance used only as an
explicit degraded fallback when routing is unavailable. The default
`mapbox/driving-traffic` profile uses traffic-aware estimates.

Already-assigned stations are removed before any paid request. The remaining
stations are ordered by straight-line distance and sent to the Matrix API in
small one-destination batches. Search stops as soon as a nearby batch provides
enough reachable stations. The Directions API is called only for stations that
win the atomic assignment. Its output includes travel distance and duration, a
GeoJSON route for the map, and Mapbox turn instructions requested in Hebrew.
An event away from the road network also includes an unverified off-road
segment from the snapped road point to the incident.

Distinct from `response_planner/`, which says *what kind* of unit is needed.
This says *which one*, and how it gets there.

## Allocation bases

Fire keeps its existing operational-risk ordering and temporary
`STATIONS_REQUIRED_BY_RISK` station counts unchanged.

Earthquake uses the explicit EcoGuard policy
`earthquake_minimum_response_v1`. For each planner-recommended unit backed by
an existing station catalog (`fire_department`, `police`, or
`medical_services`), it requests exactly one available station. This is an
EcoGuard minimum-response allocation policy, not an official government
dispatch quantity. Other recommended capabilities remain visible as
unsupported and are never silently mapped to another station type.

Earthquake claims persist `risk_score` and `risk_level` as null. Policy-driven
requests follow Fire requests in a mixed batch; among Earthquake requests they
sort by the most urgent planner action, then `queued_at`, then incident id.
Fire-to-Fire ordering is unchanged.

Station details are cached in each allocator process because they are static
reference data. Active claims are always read from and written to PostgreSQL,
whose partial unique indexes prevent two allocator processes from assigning
the same station at the same time. Nothing in the live pipeline calls the
allocator yet, and flood `LineString` routing is intentionally out of scope for
this version.
