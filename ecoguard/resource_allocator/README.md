# resource_allocator/

Decides which actual stations answer a response plan. Available stations are
ranked by Mapbox road travel time, with straight-line distance used only as an
explicit degraded fallback when routing is unavailable. The default
`mapbox/driving-traffic` profile uses traffic-aware estimates.

Already-assigned fire and MDA stations are removed before any paid request.
Police allocation represents the whole station's responsibility rather than a
vehicle, so a station may receive several incidents. The allocator first finds
the town covering the event, restricts police candidates to the stations linked
to that town, and ranks multiple responsible stations by Mapbox travel time. It
uses the nearest full police station only when no usable responsibility link
exists.

Candidates are ordered by straight-line distance and sent to the Matrix API in
small one-destination batches. Search stops as soon as a nearby batch provides
enough reachable stations. The Directions API is called only for stations that
win the atomic assignment. Its output includes travel distance and duration, a
GeoJSON route for the map, and Mapbox turn instructions requested in Hebrew.
An event away from the road network also includes an unverified off-road
segment from the snapped road point to the incident.

Distinct from `response_planner/`, which says *what kind* of unit is needed.
This says *which one*, and how it gets there.

Station details are cached in each allocator process because they are static
reference data. Active claims are always read from and written to PostgreSQL.
Partial unique indexes prevent concurrent double assignment of fire and MDA
stations and make a police incident/station pair idempotent. Flood `LineString`
routing is intentionally out of scope for this version.
