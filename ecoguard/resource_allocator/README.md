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
reference data. Active claims are always read from and written to PostgreSQL.
Partial unique indexes prevent concurrent double assignment of fire and MDA
stations and make a police incident/station pair idempotent.

Closing an incident releases every active allocation in the same database
transaction. For Fire and MDA this makes the station available again; for
Police it closes only that incident/station responsibility record. Released
rows remain as allocation history. Incident merging does not invoke this
release path.

## Flood road response sites

`FloodRoadTargetAgent` identifies where a Flood allocation could be sent. It
does not infer inundation. Until an operational policy source is available, the
allocator uses a deterministic fallback of one responsible police station per
Flood incident, for every supported severity:

| Severity | Police stations |
|---:|---:|
| 3 (Q10) | 1 |
| 4 (Q20) | 1 |
| 5 (Q50) | 1 |
| 6 (Q100) | 1 |

This is a station responsibility assignment, not a vehicle count. One police
station owns all retained road-response sites for the incident. The station may
also cover other active incidents; the active
`(incident_id, police_station_id)` pair remains unique so retries are
idempotent.

The Flood handler preserves the incident snapshot and the scheduler forwards
processing results without interpreting them. `ResourceAllocationAgent` owns
the whole allocation operation: it invokes road targeting, verifies candidates,
selects the highest-priority verified response site, and atomically assigns the
responsible police station. All other verified sites are retained in
`covered_response_site_ids`; they do not create additional station
assignments.

When no verified road site exists, allocation does not stop. The allocator uses
the highest-severity hydrometric station location as a
`hydrometric_station_fallback`, assigns one police station, and requests a road
route toward the gauge. Mapbox's snapped destination is only the last known
point on the routable road network. The route is therefore marked
`partial_offroad`, `road_access_verified=false`, and
`requires_field_access_confirmation=true`. A straight GeoJSON
`offroad_segment` connects that road point to the gauge for display, but it is
an unverified geometric estimate: it does not prove that a legal, safe or
passable field exit exists there. If no hydrometric station location is
available at all, allocation is skipped with an explicit one-station police
shortfall.

For a gauge with a confirmed stream match, it unions every `streams` feature
with the matched `water_source_id`. It never follows `draining_water_id`, so a
larger receiving river is not treated as flooded. PostGIS intersects that one
stream with the locally imported `road_segments` layer. Point intersections
remain points; a linear road/stream overlap is represented by its midpoint.

Without a confirmed stream, the agent looks for roads within 30 m of the gauge.
Only when that returns nothing does it expand to the detector's declared gauge
precision, capped at 250 m. The returned point is the closest point on the road,
and expanded matches carry lower local confidence.

Road classes follow the Mapbox Streets vocabulary:

* `motorway`, `trunk`, `primary` and `secondary`, including their `_link`
  variants, are always relevant.
* `tertiary` is relevant inside a town and for severity level 5 or 6 (Q50/Q100).
* Vehicle-accessible `street` and `street_limited` are relevant only inside a
  stored town outline.
* `service`, `track`, `pedestrian` and `path` are never allocation targets.

There is no 1.5 km clustering. Only duplicate representations of the same road
crossing within 75 m are collapsed; different roads remain separate response
sites. Every retained point is queried against Mapbox Streets. The local
intersection remains `crossing_location`, while Tilequery's nearest point on
the compatible Mapbox road becomes `allocation_location`. A missing or
conflicting Mapbox match keeps the site visible but sets
`allocation_eligible=false`.

Road lines are loaded with:

```text
python -m ecoguard.scripts.import_flood_roads roads.geojson --source openstreetmap
```

The importer accepts LineString/MultiLineString GeoJSON and maps common OSM
`highway` values to Mapbox road classes. Apply the `flood_road_segments`
migration before importing. Road discovery returns a stream-access warning even
when no road site exists, so hikers in the channel are not silently omitted.
