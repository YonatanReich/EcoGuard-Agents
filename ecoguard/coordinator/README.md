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

## Not built yet

The merge itself — grouping corroborating signals into one incident, giving it
a stable identity, and deciding when an incident is updated versus superseded.
