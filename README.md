# EcoGuard Agents

Welcome to EcoGuard Agents, a multi-agent system for managing environmental crises.

The system currently handles fires, floods, air pollution and earthquakes, and
monitors the level of the Kinneret. It watches Israel continuously, decides on
its own when something is worth an operator's attention, and presents what it
found on a live map.

## How each event is monitored

Every hazard is watched differently, because the evidence that something is
happening is different in each case.

### Fires

Fires are tracked from space. NASA's satellite fire service reports thermal
hotspots across the whole country several times a day, and heat is the earliest
honest evidence of a fire: it appears long before anyone calls it in, and it
does not depend on someone being there to see it. Places that run hot every
night, such as industrial flare stacks, are suppressed unless a reading looks
different from what that location normally does.

Detecting a fire is only half the question. To say what it will do next, the
system reads wind, temperature and humidity from the weather service, and land
cover and terrain from satellite imagery. Land cover is converted into how much
fuel is on the ground and how easily it burns, and the spread is worked out with
the standard surface-spread equations used in published fire research. The
result is turned into named places: which settlements lie in the path, and
roughly how long until the fire edge reaches them.

Fire risk is kept strictly separate from fire detection. A trained model scores
how dangerous conditions are at any point from 44 measurements, so that
"conditions here are dangerous" is never presented as "something here is
burning".

### Floods

The Water Authority publishes stream flow from its gauging stations every ten
minutes. Each reading is compared against that station's own official flood
thresholds, which are set by how rare a flow of that size is at that specific
stream. Two consecutive readings must cross the threshold before anything is
raised, so a single faulty reading from one sensor cannot start an alert.

### Air pollution

The Ministry of Environmental Protection operates monitoring stations that
report pollutant concentrations continuously. A single number means nothing on
its own, so every reading is compared against five years of history at that same
station for that same month and hour, since pollution follows strong seasonal
and daily patterns. An unusual reading is only published once the Ministry's own
official air quality index confirms it, which keeps the map free of statistical
noise that carries no health meaning.

### Earthquakes

The Geological Survey of Israel publishes seismic events as they are recorded,
and the system reads that feed every few minutes. Anything below magnitude 3.5
is recorded but not raised, because smaller tremors are common and are not felt.

### The Kinneret

The Water Authority publishes one lake level per survey day through the national
open data portal. This is not an emergency feed and is not treated as one. It is
a single figure for the whole lake, tracked for long-run context on water levels
rather than for incident response.

### Reports from people

Alongside the instruments, the system reads national news feeds and public
Telegram channels. These are the only sources that can describe something no
sensor measures, such as a road closure or an evacuation. Every message is
classified by hazard and location, and messages are treated as unconfirmed until
instrument data or a second source agrees with them. The source of each message
is recorded, including whether the channel is an official body or an unofficial
aggregator.

## Architecture



The stages never call each other. Each one reads what the previous stage wrote
to the shared store and writes its own result back. A stage that fails therefore
holds up only its own work, and recovers on its next run without anything having
to be restarted.

**Collection** reaches out to the outside world, and is the only part of the
system that does. Each source is on its own timer, set by how often that source
actually publishes something new, and each collector stores raw readings without
interpreting them.

**Detection** reads stored readings and decides which ones are unusual. There is
one detector per hazard, each with its own rules, and each runs independently so
that a failure in one does not blind the others.

**Coordination** turns detections into incidents. Several detectors can see the
same event, and the same event can be reported many times, so this stage merges
duplicates, keeps an incident open while evidence keeps arriving, closes it once
things go quiet, and links incidents that caused one another.

**Analysis** works out what an incident means: how severe it is, what it is
likely to do next, and who is nearby. Where a component cannot be computed, it
is reported as unavailable with a reason, rather than filled in with a guess.

**Planning** drafts the response. Every recommendation is grounded in published
emergency protocols and cites the passage it came from. If no protocol covers
the situation, the system says so instead of inventing advice.

**Allocation** assigns real units to emergency incidents, choosing the nearest
fire, police and ambulance stations by actual road travel time, and reserving
them so that two incidents cannot be given the same crew.

**Delivery** serves the finished results over HTTP to the dashboard. This stage
does no analysis of its own; it reads what the pipeline already produced, so the
dashboard stays fast no matter how much work the pipeline is doing.

## How the system decides what to show

An operations dashboard is only useful if what appears on it is worth reacting
to, so several checks stand between a reading and the map.

- A reading must be unusual for its own location and time of year, not merely
  high in absolute terms.
- Several reports of the same event become one incident, not several.
- Conditions that make a hazard possible are kept separate from evidence that
  it is happening.
- Some hazards require official confirmation before they are published at all.
- Anything the system could not establish is labelled as unavailable, with the
  reason, instead of being quietly omitted.

## Deliberate limitations

- Coverage is Israel only. Requests outside the national bounding box are
  rejected rather than answered with unreliable results.
- The system supports decisions; it does not dispatch anyone. Allocation
  reserves units in its own records and issues no instruction to any real crew.
- Public Telegram channels are treated as unofficial. The national fire service
  has no official channel, so the fire text source is an aggregator and is
  labelled as one throughout.
- The Kinneret feed reports one figure for the whole lake, not a measurement at
  any particular point.

## Running it

Requires Python 3.14, Node.js 22 or newer, and a PostgreSQL database with
PostGIS.

```bash
python -m venv venv
venv\Scripts\activate          # macOS or Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # then fill it in
alembic upgrade head
uvicorn ecoguard.api.main:app
```

```bash
cd ecoguard/frontend
npm install
npm run dev
```

The dashboard is at http://localhost:5173 and the backend at
http://127.0.0.1:8000.

Only the database connection is required. Every other key in `.env.example`
enables one part of the system, and that part is skipped, with a note in the
startup log, when its key is absent.

Starting the backend also starts the collection timers, so **run exactly one
backend against a given database**. Two of them would do the same work twice.

Before a demonstration, run the preflight check, which reports the things the
application cannot report about itself:

```bash
python -m ecoguard.scripts.preflight
```

## Technology

Python, FastAPI and PostgreSQL with PostGIS on the backend; React, TypeScript
and Mapbox on the front end; Claude for text classification, risk analysis and
response planning; Mapbox routing
for travel times.
