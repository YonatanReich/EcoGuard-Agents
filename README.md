# EcoGuard Agents

EcoGuard is a multi-agent system for environmental emergencies in Israel. It
continuously collects data from satellites, weather and hydrology services,
seismic and air-quality networks, and Telegram and news channels. From that it
detects fires, floods, earthquakes and air pollution, merges duplicate reports
into incidents, and assesses their risk. For each incident it drafts a response
plan grounded in published emergency protocols and assigns the nearest fire,
police and MDA stations by road travel time. Operators follow all of it on a
live map dashboard.

## Structure

Everything lives under `ecoguard/`, roughly in pipeline order:

```
ecoguard/
  collection/          scheduled collectors, one folder per source
  detectors/           find candidate events in the collected data
  coordinator/         merge duplicate candidates into incidents
  analyzers/           situation, risk and spread for each incident
  response_planner/    response plans, grounded in protocol text
  resource_allocator/  choose the stations and routes that respond
  api/                 FastAPI app (HTTP layer only)
  frontend/            React dashboard
  database/            models, repositories, Alembic migrations
  shared/              contracts and helpers used by several stages
  scheduler.py         timers for collection and detection
  scripts/             command-line jobs: reference-data loaders, demo seed
  research/            offline model training and evaluation
  data/                reference data and the protocol corpus
  docs/                design notes
  tests/
```

## Tech stack

- **Backend:** Python 3.14, FastAPI, Uvicorn, APScheduler, SQLAlchemy 2, Alembic
- **Database:** PostgreSQL with PostGIS (GeoAlchemy2, psycopg 3)
- **AI:** Claude through the Anthropic SDK, for text classification, risk analysis and response planning
- **Data and ML:** NumPy, SciPy, scikit-learn, rasterio, Telethon for Telegram
- **Frontend:** React 19, TypeScript, Vite, React Router, Mapbox GL, deck.gl
- **Routing:** Mapbox Directions and Matrix APIs
- **Deployment:** run locally and shared over a Pinggy tunnel, with the database on Neon

## Running locally

You need Python 3.14, Node.js 22+ and a PostgreSQL database with PostGIS.

**Backend**

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # then fill it in
alembic upgrade head
uvicorn ecoguard.api.main:app
```

Leave `--reload` off unless you are editing backend code. Every restart reboots
the scheduler and re-runs the Claude reachability probe, and a reload triggered
mid-wave abandons work already paid for.

Before a demo, run the preflight. It checks the things the app cannot report
about itself — database reachable, Claude key still funded, no second backend
holding the wave lock, and which collectors have gone stale:

```bash
python -m ecoguard.scripts.preflight
```

It exits non-zero when something a demo needs is broken, and the most common
failure is an exhausted Claude balance, which otherwise looks exactly like a
quiet day: every planner reports `failed` and the map simply shows nothing.

**Run exactly one backend at a time.** Each process starts its own scheduler,
and two schedulers pointed at the same `DATABASE_URL` build plans for the same
incidents — every model call paid twice. There is a Postgres advisory lock on
the detection wave that makes the second process skip rather than duplicate,
but it only covers processes sharing a database.

The API runs at http://127.0.0.1:8000. Only `DATABASE_URL` is required. The
other keys in `.env.example` (Anthropic, NASA FIRMS, Telegram, Mapbox and so on)
each enable one part of the system, and that part is skipped when its key is
missing.

Point `DATABASE_URL` at your own database. The backend starts the collection
scheduler on boot, and the scheduler writes to that database.

**Frontend**

```bash
cd ecoguard/frontend
npm install
npm run dev
```

Put `VITE_MAPBOX_KEY=<your Mapbox public token>` in `ecoguard/frontend/.env`,
then open http://localhost:5173. The dev server sends `/api` requests to your
local backend on port 8000. Set `VITE_API_TARGET` to point somewhere else.

**Sharing it with testers**

The project is not hosted. To let someone outside the machine see it, start the
backend and frontend as above, then open a tunnel to the Vite port:

```bash
ssh -p 443 -R0:localhost:5173 a.pinggy.io
```

Pinggy prints an `https://<random>.pinggy.link` URL — that is what testers open.
Requests to `/api` go through Vite's proxy to the local backend, so only the one
port needs tunnelling. The tunnel's hostname changes every session, which is why
`vite.config.ts` allowlists the Pinggy suffixes rather than a fixed host, and why
the API's CORS rule matches them by pattern.

The free tunnel expires after an hour; re-run the command for a new URL. Nothing
in the app stores the tunnel hostname, so a new URL needs no code change.

**Demo**

`/demo` shows fabricated incidents from a separate database. Set
`DEMO_DATABASE_URL` in `.env` and seed it with
`python -m ecoguard.scripts.seed_demo`.
