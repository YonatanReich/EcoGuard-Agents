# coordinator/

Detectors fire independently and will report the same event more than once: a
satellite hotspot, three Telegram messages and a station reading can all be one
fire. This is where duplicates are merged into a single incident, candidates
from different sources are correlated, and one event gets one identity before
anything downstream analyses it.

It sits between `detectors/` and `analyzers/` because analysing the same fire
four times is both wasteful and misleading — four assessments look like four
fires to whoever is reading.

## The contract it consumes

Everything here speaks one language, defined in `ecoguard/shared/`:

- **`cells.py`** — the cell. Deliberately coarser than every source, because
  its job is to be *shared*, not precise. It is the spatial join key that makes
  "same place" answerable across hazards.
- **`signals.py`** — `CellSignal`, the only shape this stage consumes. A
  detector for any hazard emits these and nothing else.

Both live in `shared/` rather than here because detectors *produce* them and
this stage *consumes* them — two stages, so one level up, per the rule in
`shared/README.md`.

## The idea that makes hazards comparable

Not magnitude, **rarity**. Kelvin, millimetres and micrograms cannot be
compared; "a 1-in-500 reading for this cell at this time of year" can, and
means the same thing for all three.

Rarity is kept strictly apart from **severity**. 25 °C in a Negev January is
extremely rare and harmless; 40 °C in a Negev August is statistically dull and
is what burns the country down. Detectors answer rarity. Analysers answer
severity. Collapsing them loses one case or the other.

## Why corroboration is the whole point

A rarity threshold is a false-alarm budget. At 0.999 across 1,174 cells checked
hourly, chance alone yields ~28 signals a day per variable. That is only
workable because agreement multiplies: two *independent* sources at 0.999 in
the same cell is a one-in-a-million coincidence.

So `corroborates()` deliberately does **not** filter on `reportable`. Two weak
signals agreeing is evidence; discarding them individually first throws away
exactly what this stage exists to find.

## What runs

`agent.coordinate()` is the entry point: signals in, two queues of incidents
out. One run closes what has gone quiet, matches each signal to an open
incident or opens a new one, merges causally linked incidents into hybrids, and
queues the result. `incidents.py` is the store, `matching.py` the dedup rules,
`packaging.py` the causal merge, `queues.py` the routing.

## Not built yet

Corroboration is not yet *required*. `coordinate()` opens an incident for every
signal it is handed, so the "two weak sources agreeing" case the section above
describes is unreachable from here — detectors filter on `reportable` before
calling, and a pair of sub-threshold signals never arrives to be combined.
Closing that gap means letting detectors emit below the bar and having this
stage promote only what corroborates.
