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
stations and make a police incident/station pair idempotent.

## Flood road response sites

`FloodRoadTargetAgent` identifies where a Flood allocation could be sent. It
does not infer inundation. Until an operational policy source is available, a
deterministic fallback converts severity into station counts:

| Severity | Fire/rescue stations | Police stations | MDA stations |
|---:|---:|---:|---:|
| 3 (Q10) | 1 | 1 | 0 |
| 4 (Q20) | 2 | 1 | 1 |
| 5 (Q50) | 3 | 1 | 1 |
| 6 (Q100) | 4 | 1 | 2 |

These are station assignments, not vehicle counts. Police is always one
responsible station per incident; that station owns all retained road-closure
sites. Fire/rescue and MDA also allocate once per incident, never once per
crossing.

The Flood handler preserves the incident snapshot and the scheduler forwards
processing results without interpreting them. `ResourceAllocationAgent` owns
the whole allocation operation: it invokes road targeting, verifies candidates,
selects the most important response site, and reserves the explicit fallback
quantities. Without a verified site no automatic station allocation occurs.

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
