# EcoGuard

A system that watches Israel for fires, floods, earthquakes and air pollution,
and tells an operator what is happening and what to do about it.

## How it works

Everything flows in one direction. Each stage does one job and hands on.

```
collectors -> detectors -> coordinator -> analyzers -> planners -> allocator -> dashboard
```

1. **Collectors** fetch readings from outside providers - satellites, gauges,
   monitoring stations, weather services, news feeds, Telegram - and store them.
   They never decide anything.
2. **Detectors** ask one question of those readings: is this unusual? Unusual
   means unusual *for this place at this time of year*, which needs a baseline,
   not just a threshold.
3. The **coordinator** decides whether several unusual readings are one event or
   several. Without it, one fire becomes forty events, because a fire produces a
   satellite detection every half hour, a dozen messages and an hourly weather
   anomaly - all describing the same thing.
4. **Analyzers** work out how bad the event is and what it threatens.
5. **Planners** say what should be done, grounded in published emergency
   protocols - and may only recommend what those protocols actually say.
6. The **resource allocator** says who should do it: which stations, how far
   away, how long to get there.
7. The **dashboard** shows the result on a map.

## The folders

| Folder | What it holds |
|---|---|
| `collectors/` | Everything that reaches out to an outside provider |
| `detectors/` | Deciding which readings are unusual |
| `coordinator/` | Deciding what is one event and what is several |
| `analyzers/` | How bad it is and what it threatens |
| `planners/` | What should be done about it |
| `resource_allocator/` | Who should do it, and how long they need |
| `database/` | The store: the connection, the schema history, and every query |
| `shared/` | Pieces every layer uses - the grid, the signal shape, weather, protocols |
| `api/` | The HTTP layer the dashboard calls |
| `frontend/` | The dashboard itself |
| `data/` | Reference data and the emergency protocol corpus |
| `demo/` | Running the pipeline against an authored dataset, live |
| `scripts/` | Commands run by hand: building baselines, importing files, pre-demo checks |
| `docs/` | Longer write-ups that do not belong beside the code |
| `tests/` | The test suite |

Loose at the top: `scheduler.py` holds the timers, `retention.py` decides how
long each source is kept, and `paths.py` says where things live on disk.

## Two ideas the whole system rests on

**The cell.** Nothing here observes the same thing at the same resolution - a
satellite sees a 375 m pixel, a station sees a point on a roof, a weather model
sees a 10 km grid. Everything is resolved onto one shared grid of cells, which
is what makes "unusual heat in cell X" and "unusual PM2.5 in cell X"
comparable statements at all.

**Rarity, not magnitude.** Brightness is kelvin, rain is millimetres, PM2.5 is
micrograms. None compare directly. So detectors report not *how much* but *how
unusual* - a number between zero and one - and a one-in-500 reading of one is
the same strength of claim as a one-in-500 reading of another.

## Conventions

- **Failures produce nothing, never a default.** An analyzer that cannot reach
  its model reports that it failed. It does not return a plausible-looking
  score, because a wrong number that looks right is worse than an absent one.
- **Anything a model says is checked.** A recommendation that cites no protocol,
  or quotes one inaccurately, is rejected before an operator sees it.
- **Documentation lives with the code.** Every folder has a README, every file
  says what it is for, and every function says what it does.

## Running it

```
alembic upgrade head              # bring the database up to date
python -m ecoguard.scripts.preflight   # is this machine ready?
uvicorn ecoguard.api.main:app --reload # the backend
npm --prefix ecoguard/frontend run dev # the dashboard
```

To show the system working without waiting for something to happen, press
**Run Demo A** on the dashboard home page. It points the detectors at an
authored dataset and runs the real pipeline over it, live, until you press
**End Demo**.
