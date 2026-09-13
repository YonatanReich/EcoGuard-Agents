# Offline fire-risk grid

The MVP grid uses deterministic 5 km cell centroids inside the same conservative
rectangle used by the historical FIRMS pipeline: `34.2–35.9 E` and
`29.4–33.4 N`. There is no authoritative nationwide service-area polygon in
the local project cache. The official settlement polygons cannot be used as a
national boundary because that would exclude forests, reserves, agricultural
land, and other open areas.

Cells whose centroid has a recognized non-water ESA WorldCover class are active.
A water-centroid cell is also recovered when either its centroid is inside/on
the EcoGuard service area and at least 25% of its footprint is recognized
in-service land, or at least 20% is recognized in-service land and at least 90%
of all recognized land in the cell lies inside the service area. Recovered cells use the
dominant valid land class and the nearest valid land pixel to the centroid for
DEM elevation and slope, and store `activation_method=water_centroid_land_overlap`.
Cells with no recognized WorldCover class remain
inactive. This is a land/service-coverage mask, **not an
authoritative political boundary**. Consequently, non-water cells near the
rectangle edges can lie outside Israel. A later grid-version migration should
apply an authoritative national service-area polygon without changing the
meaning of the static predictors.

For active cells, the offline builder reads only existing cached rasters:

- ESA WorldCover 2021 v200 for the raw class and exact 11 model one-hot flags.
- Copernicus DEM GLO-90 for centroid elevation.
- The existing 3×3 Horn-neighborhood implementation for slope in degrees.

It never downloads missing tiles. A missing tile stops the atomic build and
reports the required coverage; an existing database is not replaced.

The generated SQLite file is `data/generated/fire_risk_grid.sqlite`. The
`risk_grid_cells` table stores stable cell identity, location, activity state,
static features, source versions, build time, and feature status. Routine risk
scans should read these values locally and must not reacquire static data.

Build:

```powershell
python -m scripts.build_fire_risk_grid
```

Inspect one active cell:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/generated/fire_risk_grid.sqlite'); print(c.execute('SELECT * FROM risk_grid_cells WHERE active=1 LIMIT 1').fetchone())"
```
