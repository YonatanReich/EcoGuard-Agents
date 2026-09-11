# EcoGuard service-area reference

`ecoguard_service_area.geojson` is derived locally from **Natural Earth
1:10m Admin-0 Countries — Israel POV** (`ne_10m_admin_0_countries_isr.zip`).

The runtime geometry is the union of every source record where
`SOVEREIGNT == "Israel"`. EcoGuard uses this geometry solely as its
operational application/service area. It is not presented as a legal or
political boundary claim.

The 5 km risk scan and rolling weather updater include a grid cell when its
centroid is inside/on the service-area polygon **or** at least 25% of its 5 km
footprint overlaps that polygon. Other cells are excluded before weather work,
feature construction, or model evaluation.

## Emergency service stations

`stations_seed.json` holds the finished contents of the three station tables —
fire, police and Magen David Adom — and migration `0006` loads it. Running
`alembic upgrade head` on an empty database therefore produces both the schema
and the data, with no extra step.

| table | rows | located | positions |
|---|---|---|---|
| `fire_stations` | 118 | 108 | 57 on their mapped OSM building, rest from the published address |
| `police_stations` | 147 | 147 | every one published by the Israel Police |
| `mda_stations` | 168 | 119 | 36 on their mapped OSM building, rest from the published address |

The scripts that built this are gone: the rosters are static, and rebuilding
them meant geocoding several hundred Hebrew addresses against a rate-limited
public gazetteer and reconciling the results against OpenStreetMap. That work
does not need repeating, so its output ships instead of its inputs.

**Position quality is recorded per row**, in `fire_stations.geocode` and
`{police,mda}_stations.source`:

- `building` — matched to the mapped station in OpenStreetMap. This is the
  station itself.
- `street` — the published address resolved to a road. The right street, not
  the building.
- `city` — the town centroid. In a large city this is kilometres from the
  station, and the map fades these rather than drawing them as though they were
  surveyed.
- `exact` — published by the service itself, which is every police station.

Anything reasoning about dispatch distance should read that field rather than
treat all rows alike. 59 stations have no coordinates at all, because their
published entry gives a junction or a regional council and no address a
gazetteer can resolve; they are counted but not drawn.
