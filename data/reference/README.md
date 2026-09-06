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
