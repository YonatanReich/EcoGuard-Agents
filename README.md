# EcoGuard Agents

EcoGuard Agents is a multi-agent system for real-time environmental crisis management in Israel.

The system will collect environmental data, detect crisis events, analyze risk levels, recommend relevant authorities to activate, and generate response plans.

## Project Structure

- backend: FastAPI server and internal APIs
- frontend: React web dashboard and map interface
- agents: Autonomous agents and risk analysis logic
- tests: Automated tests
- docs: Project documentation, sprint summaries and architecture files
## Backend

The backend is built with FastAPI.

### Setup

Create and activate a virtual environment:

```bash
python -m venv venv
.\venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### Configure API keys

Copy `.env.example` to `.env` at the repository root and fill it in. `.env` is
gitignored; never commit real keys.

```bash
cp .env.example .env
```

| Variable | Needed for | Without it |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Risk analysis and response planning | Events are detected but not assessed; status reports `missing credentials` |
| `ANTHROPIC_WORKSPACE_ID` | Anthropic identity-linked API keys only | Omit it for ordinary organisation keys |
| `IMS_API_TOKEN` | IMS-backed Air Pollution wind evidence | Wind, transport corridor, settlement screening and corridor population remain unavailable |
| `NASA_FIRMS_API_KEY` | Satellite fire detection | `/api/detected-events` cannot detect anything |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | Telegram fire intelligence listener | That standalone script cannot run |

The frontend map additionally needs `VITE_MAPTILER_KEY` in
`frontend/.env.local` — see the frontend section below.

Every agent degrades rather than crashing when a key is absent, so the app still
runs with none of them set. It just reports honestly about what it could not do.

The `AIR_POLLUTION_TRANSPORT_*` values in `.env.example` are the current v1
deterministic screening policy: a 45-degree half-angle, 10 km maximum distance,
eight arc segments, a 30-minute wind-age limit and a 0.5 m/s minimum wind
speed. They define possible-transport screening geometry. They are not
plume-physics constants and do not establish a source, plume or exposure.

### Run the tests

```bash
pytest
```

The whole suite runs offline — no API keys, no network. To verify the Claude
integration end to end (a real call, structured output, citation verification,
and prompt caching), run the smoke check, which needs `ANTHROPIC_API_KEY`:

```bash
python scripts/claude_smoke_check.py
```

### Run backend locally

```bash
uvicorn ecoguard.api.main:app --reload
```

### Run frontend locally
```bash
cd frontend
npm run dev
```

The API will be available at:

```text
http://127.0.0.1:8000/
```

Expected response:

```json
{
  "message": "EcoGuard Agents API is running",
  "status": "success"
}
```

## API Endpoints

### 1. Get Unified Environmental Data
`GET /api/environmental-data`

#### Description
Unifies stored weather observations with live regional geospatial context around a specific coordinate. Inputs are validated strictly within Israel's boundaries.

The two halves no longer work the same way. `WeatherDataAgent` **reads the collection layer's store** rather than calling Open-Meteo — the coordinate is answered by the 5 km grid cell containing it, and `metadata.services.weather.observation` names that cell, its distance in metres, and when the reading was taken. `GeospatialContextAgent` still calls OpenStreetMap Overpass live, because nothing collects that on a timer, and it is what makes this endpoint slow.

Two consequences worth knowing:

* `weather.forecast.daily` is **empty**. The store holds observations, and a forecast is not one.
* A coordinate with no cell within 5 km carrying a reading under 6 hours old returns `collection_status: "failed"` for the weather half, rather than reaching out to fetch one.

See [`docs/weather_collection.md`](docs/weather_collection.md) for the collection layer.

#### Query Parameters

| Parameter | Type | Required | Default | Validation / Restrictions | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `latitude` | Float | No | `31.783333` (Jerusalem) | Must be between `29.45` and `33.35` | Geographical latitude within Israel's borders (South to North). |
| `longitude` | Float | No | `35.216667` (Jerusalem) | Must be between `34.26` and `35.90` | Geographical longitude within Israel's borders (West to East). |

#### HTTP Response Status Codes

* **`200 OK`**
  The request was successful. A unified JSON object containing metadata, services health status, core weather tracking, and geospatial elements is returned.
  
* **`422 Unprocessable Entity`**
  Input validation failed. This happens automatically if the coordinates are missing, malformed, or fall completely outside Israel's bounding box.
  
* **`502 Bad Gateway`**
  Service failure. Triggered when both external downstream environmental providers (Open-Meteo and OpenStreetMap Overpass API) fail or time out simultaneously.
  
* **`500 Internal Server Error`**
  An unexpected server-side error occurred. For security and to prevent information disclosure vulnerabilities, the detailed stack trace is masked from the client and securely logged on the backend console.

---

### 2. Detect, Assess and Plan for Fire Events
`GET /api/detected-events`

#### Description
Runs the full crisis pipeline for one coordinate: `FireDetectionAgent` looks for
NASA FIRMS satellite hotspots and enriches them with GWIS/EFFIS fire weather,
Open-Meteo conditions and OpenStreetMap context; `RiskAnalysisAgent` scores the
operational risk; `ResponsePlanningAgent` produces the units to activate and the
actions to take.

Both reasoning agents call Claude and are **grounded in retrieved protocol
text** rather than the model's general knowledge. Passages are retrieved from
the committed corpus in [`data/protocols/`](data/protocols/) by BM25, the schema
requires at least one citation, and every citation is verified in Python against
the passage it claims to quote. A result whose citations do not verify is
discarded rather than served.

#### Query Parameters

| Parameter | Type | Required | Default | Validation / Restrictions | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `latitude` | Float | No | `31.783333` (Jerusalem) | Between `29.45` and `33.35` | Latitude within Israel's borders. |
| `longitude` | Float | No | `35.216667` (Jerusalem) | Between `34.26` and `35.90` | Longitude within Israel's borders. |
| `radius_km` | Float | No | `5.0` | Between `1` and `50` | How far from the point a hotspot counts as relevant. |
| `day_range` | Integer | No | `2` | Between `1` and `10` | How many recent days of satellite data to inspect. |
| `include_analysis` | Boolean | No | `true` | — | Set `false` to skip both model calls for a fast, detection-only response. |

#### HTTP Response Status Codes

* **`200 OK`**
  The pipeline ran. This includes the cases where nothing was detected
  (`events: []`) and where satellite detection failed (`events: []` with
  `collection_status: "failed"`). Unlike `/api/environmental-data`, provider
  failure is reported in the body rather than as a 502 — the dashboard fetches
  this on page load and has no user-visible error path, so a 5xx would blank the
  map with no explanation.

* **`422 Unprocessable Entity`**
  A parameter fell outside the ranges above.

* **`500 Internal Server Error`**
  An unexpected server-side error. The detail is masked and the exception logged.

#### Note on missing values

`risk_score` and `risk_level` are `null` whenever the analysis did not succeed —
never `0`, never `"low"`. Absence of a detection is not evidence of low risk, and
a provider outage is not evidence of safety. The dashboard renders that state in
grey rather than defaulting it to a colour that implies an all-clear.

#### Performance

This endpoint is slow: typically 20-90 seconds. The OpenStreetMap Overpass
lookup alone can take 30 seconds under load, and each of the two model calls adds
several more. Use `include_analysis=false` for a fast map render. A
background-job endpoint would be the proper fix and is not implemented.

The full field-by-field contract is in [`docs/api_contract.md`](docs/api_contract.md) §5.

---
### 3. Summarise a Drawn Area
`POST /api/area-summary`

#### Description
Aggregates everything in the store over a polygon the operator drew on the map —
freehand, rectangle or circle. This replaced clicking a single coordinate: a
point can only say what the temperature is *there*, while the operational
question is how many people are inside a shape and what the weather is doing
across it.

Nothing is fetched from an upstream provider, so unlike the two endpoints above
this one answers in milliseconds. Every figure is a PostGIS aggregate:

| Figure | Source | How |
| :--- | :--- | :--- |
| `population` | `population_cells` | Summed with **area weighting** — a cell half inside the polygon contributes half its people |
| `weather` | `observations` (`source='weather'`) | Mean of the newest reading per 5 km cell within half a grid step of the polygon. Wind direction is averaged as a vector, not as a number |
| `fire_danger` | `observations` (`source='fire_weather'`) | Mean FWI over the same cells, plus the single worst band inside them |
| `terrain` | `surface_cells` | Mean elevation and slope, the relief (min/max elevation), the **steepest** face inside the polygon, and the bearing a fire would run |
| `fuel` | `surface_cells` | Area-weighted cover mixture, the dominant class, and the burnable and built-up shares |
| `stations` | `fire_stations`, `police_stations`, `mda_stations` | Point-in-polygon counts |
| `area_km2` | the polygon | `ST_Area` on the spheroid |

#### Request Body

```json
{ "geometry": { "type": "Polygon", "coordinates": [[[35.0, 31.0], "..."]] } }
```

| Field | Validation |
| :--- | :--- |
| `geometry` | GeoJSON `Polygon`. Every ring closed and at least four positions; every vertex inside Israel's bounding box; at most 2,000 vertices in total |

Self-intersecting rings are accepted rather than rejected — a freehand trace
crossing its own line is the normal case, and PostGIS repairs it with
`ST_MakeValid` before measuring.

#### HTTP Response Status Codes

* **`200 OK`** — the summary. A section with no data underneath it reports
  `null` values and `cell_count: 0` rather than being omitted, so the UI can say
  "no reading here" instead of silently dropping a row.
* **`422 Unprocessable Entity`** — the geometry failed one of the checks above.
* **`503 Service Unavailable`** — the store could not be reached.

#### Loading the population grid

`population_cells` is empty until the grid is loaded. Area-summary reads then
have no contributing cells, while Air Pollution corridor analysis reports
`shared_population_grid_unavailable_or_unloaded`; neither path treats missing
reference data as a confirmed population of zero. The table holds one row per
raster pixel of a population
**count** grid, as the pixel's own footprint — the footprint, not the centroid,
is what makes the area weighting possible.

Download WorldPop's constrained, UN-adjusted 100 m grid for Israel
([`isr_ppp_2020_UNadj_constrained.tif`](https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/ISR/isr_ppp_2020_UNadj_constrained.tif),
1.9 MB), then:

```bash
alembic upgrade head
python -m ecoguard.scripts.load_population_grid data/generated/isr_ppp_2020_UNadj_constrained.tif
```

The script prints the total it loaded — 315,600 cells and 8,655,541 people for
the file above, which matches the UN's 2020 figure for Israel and is the sanity
check that the right raster went in. Pass `--coarsen 2` for 200 m cells
if the row count matters more than the resolution. It is a full reload —
`population_cells` is truncated first — because this is reference data published
once a year, not a feed.

This is a one-time deployment/reference-data prerequisite for every database
that should support Air Pollution corridor population screening. Run it only
against the explicitly intended database; the loader performs a full reload.

#### Loading the surface grid

`surface_cells` is empty until the grid is loaded, and until then `terrain` and
`fuel` report `null` with `cell_count: 0`. It holds the two *static* legs of the
fire behaviour triangle — the shape of the ground and what grows on it. The
third leg, weather, is a feed and lives in `observations`.

Neither static leg answers anything alone, which is why they share a row: a 25°
slope of bare Negev rock is not a fire, and the same slope in Carmel pine is the
2010 one.

| Column group | Source | Resolution |
| :--- | :--- | :--- |
| `elevation_m`, `slope_deg`, `slope_max_deg`, `aspect_deg` | Copernicus DEM GLO-90 | 90 m, derived then coarsened |
| nine cover fractions | ESA WorldCover 2021 v200 | 10 m, counted per cell |

Both sources are free and unauthenticated. The script fetches ten 1° DEM tiles
and three 3° WorldCover tiles (about 130 MB, cached under
`data/generated/static_environmental_sources/` and shared with the offline risk
grid). One DEM tile is open Mediterranean and is not published at all, which is
expected and skipped:

```bash
alembic upgrade head
python -m ecoguard.scripts.load_surface_grid
```

That loads 429,876 cells of about 270 m. The printed summary is the sanity
check: **-427 m to 2,306 m** (the Dead Sea shore and Hermon) and a steepest cell
of 59°. Pass `--coarsen 1` for the native 90 m grid at roughly nine times the
rows.

Four details that matter more than they look:

* Slope and aspect are computed on the **native 90 m mosaic, before**
  coarsening. Deriving them from an already-averaged surface would flatten
  every gully — the exact feature the data exists to capture.
* Each cell stores mean slope **and** max slope. On the Ramon crater rim the
  mean is 4.7° and the max is 36.2°; a fire cares about the second number, and
  an average is precisely what hides it.
* Land cover is stored as a **fraction per class, not a dominant label**. A
  270 m cell holds ~900 WorldCover pixels and is almost never pure, and the
  mixture is the signal: 55% shrubland with 33% built-up is the wildland-urban
  interface, which "shrubland" would erase. `dominant` is still returned, as
  `max()` over the mixture.
* `unmapped` is the honest remainder — nodata, plus the three WorldCover classes
  Israel has none of (snow/ice, mangroves, moss/lichen), which get no columns of
  zeroes. The nine fractions sum to 1, so a cell reading mostly-unmapped is
  visibly wrong rather than quietly short.

Cells are clipped to `data/reference/ecoguard_service_area.geojson`, so the sea
and the neighbouring countries are not stored as two million rows of nothing.
Like the population grid this is a full reload, and the ground does not move —
run it once, then only when a source publishes a new version.

Agents that hold a coordinate rather than a polygon call the repository
directly, which reports the ground a fire can reach rather than only the ground
it is on:

```python
from ecoguard.database.repositories.surface import surface_at

surface_at(32.73, 35.03)          # Mount Carmel, 500 m around the point
# {'terrain': {'elevation_m': 430.9, 'slope_deg': 12.8, 'slope_max_deg': 28.2,
#              'aspect_deg': 205.3, 'upslope_bearing_deg': 25.3, ...},
#  'fuel':    {'dominant': 'tree_cover', 'burnable_fraction': ...,
#              'built_up_fraction': ..., 'fractions': {...}, ...}}
```

`aspect_deg` is the bearing the ground **faces** (downhill); `upslope_bearing_deg`
is where a fire runs, and is reported alongside it so no caller has to remember
which way round that goes. Both are `null` on genuinely flat ground — the Dead
Sea shore returns no bearing rather than a due-north one invented from noise.

`burnable_fraction` counts wildland vegetation only: tree, shrub, grass and
crop. Built-up is deliberately excluded and reported separately — a town burns,
but it burns as a structure fire with different physics and a different
response, and folding it in would tell the analyser a suburb is a meadow.

## The Collection Layer

Seven sources, one `observations` table. Adding a source does not add a table:
a source is a value in the `source` column and a shape in the `payload` jsonb,
so the schema stops growing once the identity is right.

### Layout

Collectors are filed by the hazard they serve, and each source keeps its own
provider client next to the collector that uses it:

```
ecoguard/collection/
  base.py                    BaseCollector, the 5 km grid, service-area cells
  shared/
    open_meteo/              weather + forecast — every hazard reads these
      client.py  observations.py  forecast.py
  fire/
    firms/                   satellite hotspots    client.py  collector.py
    effis/                   published FWI band    danger.py  collector.py
    fwi/                     our own FWI system    index.py   collector.py
    gibs/                    MODIS NDVI                       collector.py
    telegram/                ground reports        listener.py collector.py
  flood/                     Water Authority hydrology catalogs and observations
  pollution/                 empty — EA-307 lands here
```

`shared/` exists because weather belongs to no single hazard: fire risk, flood
risk and pollution dispersion all read the same hourly rows, and filing it under
one of them would invite the other two to collect it again. The test for that
folder is dependency, not subject matter — a source only fire reads belongs in
`fire/` even when it sounds general.

`agents/` now holds only pipeline agents — detection, risk analysis, planning.
The provider clients that used to live there (`firms_data_agent`,
`fire_danger_agent`, `telegram_fire_listener`) were never agents in the same
sense; they were HTTP clients and parsers, and they now sit beside the
collectors that call them.

That identity is `(source, cell_id, observed_at, issued_at)`, declared
`UNIQUE NULLS NOT DISTINCT` so one table can hold both measurements and
forecasts. `observed_at` is always the hour being described; `issued_at` is the
forecast run that described it, and `NULL` means nothing described it — it was
measured. Without `NULLS NOT DISTINCT` every measured row would count as
distinct from every other and re-fetching a window would duplicate it instead
of conflicting.

| Source | Every | What it is |
| :--- | :--- | :--- |
| `telegram` | 5 min | Raw channel messages, unclassified. The only sub-hour detection path. |
| `firms` | 30 min | Satellite hotspots from **four** products — NOAA-20, NOAA-21, Suomi-NPP and MODIS. |
| `weather` | 60 min | Eleven hourly variables, backfilled to whatever is missing. |
| `weather_forecast` | 6 h | 48 hours of lead time on a ~15 km subgrid, every run kept. |
| `fire_weather` | 6 h | The EFFIS FWI danger band, as published. |
| `fwi` | 6 h | Our own Canadian FWI system — six numbers, carried day to day. |
| `vegetation` | 12 h | MODIS NDVI, the 8-day composite. |

### Why FIRMS asks four satellites

FIRMS publishes four near-real-time products for this region and we were using
one, which discarded most of the day's looks at the country for no saving — the
same key, the same bounding box, one more request each. NOAA-20, NOAA-21 and
Suomi-NPP fly the same plane about fifty minutes apart; the MODIS instruments
cross at different hours entirely.

Hotspots are grouped by cell and overpass time, **not** by satellite: two
instruments seeing one cell in one minute are seeing one fire, so they merge
into one observation and the contributing satellites travel in the payload.
Agreement between them is itself evidence — a hotspot three instruments caught
is not the same claim as one only MODIS saw.

One product failing is logged and skipped; all four failing raises, because
"no hotspots today" and "nothing could be asked" must not look alike.

Worth knowing: FIRMS near-real-time is ~3 hours behind the overpass by
definition, and the faster feeds are US/Canada only. Satellite is the
confirmation channel here, not the alarm.

### Why the FWI system is computed rather than fetched

EFFIS gives one categorical band a day. The band is the last step of six, and
the five before it are the ones carrying state:

* **FFMC** — fine dead fuels. Responds in *hours*. Decides whether a match catches this afternoon.
* **DMC** — loosely compacted duff. Responds over *weeks*.
* **DC** — deep organic matter. Responds over *months*. This is the seasonal drought memory, and it is what makes a dry August after a wet winter different from a dry August after a dry one.

`ISI` combines FFMC with wind into spread rate, `BUI` combines DMC and DC into
available fuel, and `FWI` combines those. Storing only the band kept about two
bits of the system.

These are **accumulators**, which is why the collector walks forward day by day
from wherever it left off rather than recomputing a window. A DC derived from
seven days of history is not a shallow DC; it is a different quantity wearing
the same name.

The cold-start consequence is real and every row declares it. `chain_days`
counts the consecutive days behind the value and `spun_up` is false until 60 of
them. **Until then, treat `ffmc` and `isi` as usable and `dc`, `bui` and `fwi`
as provisional** — a young chain understates drought, and mild is the dangerous
direction to be wrong in. Against EFFIS on the same day, a 7-day chain read
`moderate`/`high` where EFFIS read `extreme`, entirely through DC.

### Derived, not stored

Two things the pipeline needs that are code rather than tables:

* [`ecoguard/analyzers/emergency/fire/fuel_models.py`](ecoguard/analyzers/emergency/fire/fuel_models.py) maps cover fractions to Anderson 13 fuel-model parameters — load, bed depth, surface-area-to-volume, moisture of extinction. No spread model takes a land-cover class. Blending is over the *whole* cell, so a fifth of a cell of grass reports a fifth of grass's load; renormalising onto the burnable part would race a fire across bare desert.
* [`repositories/fire_history.py`](ecoguard/database/repositories/fire_history.py) answers prior-detection counts and, more importantly, `persistence` — whether a cell's hotspot record is a quarry or flare rather than a fire regime. It separates them by *regularity*, not count: a bad season puts many detections in a cell, but it does not put them there on two days in five for two months. Without this a detector re-raises the same industrial sites forever and its readers learn to ignore it.

### The climatology baseline

`weather_baselines` is the detector's missing denominator. Without it
"anomalous" can only mean *different from the trailing week* — and the trailing
week drifts along with whatever is happening. A heatwave that builds over six
days never looks unusual on any single one of them, and by day ten of a khamsin
the khamsin **is** the baseline. Those are exactly the slow, persistent
conditions that matter most for fire.

A climatological bucket does not drift. It is the same distribution every
September regardless of what this September is doing, so an hour is compared
against a decade instead of against itself.

```bash
python -m ecoguard.scripts.build_weather_baselines            # 10 years, ~15 min
python -m ecoguard.scripts.build_weather_baselines --years 5  # thinner, faster
```

One row per **cell × variable × month × hour** — 288 buckets per cell per
variable, each holding roughly 300 samples drawn from ten complete calendar
years of Open-Meteo's hourly archive. Five variables: temperature, humidity,
wind speed, precipitation, and vapour pressure deficit (computed from the first
two, since the archive does not serve it).

Bucketing is month **and** hour, not month alone: 35 °C at 14:00 in August is
ordinary and 35 °C at 04:00 in August is extraordinary, and a month-only bucket
averages those into one meaningless number.

Reading it:

```python
from ecoguard.database.repositories.climatology import anomalies

anomalies(32.73, 35.03, month=9, hour=12, readings={"temperature_2m": 41.0})
# {'cell_id': 'risk-05000m-...', 'assessed': {'temperature_2m': {
#     'value': 41.0, 'band': 'extremely_high', 'anomalous': True, 'z': 4.1,
#     'method': 'modified_z', 'median': 30.2, 'p95': 34.8,
#     'record_high': 40.1, 'beyond_record': True, 'samples': 300}}}
```

Two statistics, and the choice between them is load-bearing:

* The **modified z-score** (median and MAD) is the primary test. A classic
  mean-and-sigma score assumes a roughly symmetric distribution, which
  temperature obeys and precipitation flatly does not.
* MAD is zero whenever more than half a bucket is identical — the *normal*
  state of precipitation, since it does not rain in most hours. A z-score is
  undefined there, so the fallback is the **percentile band**, which still
  ranks correctly.

Band boundaries resolve ties **downward**: sitting exactly at p95 is the top of
`high`, not the bottom of `extremely_high`. That is not a detail. With strict
comparisons a dry hour in a dry bucket matches no band and falls through to the
last one, and every rainless hour in Israel reports as extreme rainfall.

`beyond_record` is reported separately from `anomalous`, because "outside
anything in ten years of this bucket" is a stronger claim than "unusual" and a
caller escalating on it should not have to infer it from a z-score.

Baselines are built on the ~15 km forecast subgrid, since climatology is a
smooth regional field — the Negev and the Galilee differ, two adjacent 5 km
cells do not. Any cell is answered by its nearest baseline cell, mapped by
arithmetic rather than a query.
