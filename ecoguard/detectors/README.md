# Detectors

The step that decides something might be happening.

A detector reads the observations a collector stored and asks one question: is
this reading unusual enough to be worth someone's attention? When the answer is
yes it emits a signal — a place, a time, a hazard and the evidence behind it —
and stops. It does not assess how bad the event is and it does not plan a
response; those come later.

Every detector remembers where it got to, so a reading is judged once and a
detector that was offline picks up where it left off rather than re-reading the
whole table.

## What is here

| Folder | What it looks for |
|---|---|
| `fire/` | Satellite hotspots that are unusual for that place, and separately, weather that would let a fire spread |
| `flood/` | Stream discharge crossing the official flood thresholds for that gauge, twice in a row |
| `air_pollution/` | A pollutant reading above what that station normally records at that hour of that month |
| `earthquake/` | New events in the national seismic feed |
| `text/` | News and Telegram messages: a model labels what each message reports, then triage decides whether anything supports it |

## Things worth knowing

Fire weather is deliberately not fire. Hot, dry, windy conditions mean a fire
*could* spread, not that one exists, so it travels as its own hazard and never
becomes a fire alert.

The text lane is the only detector that uses a language model, and the only one
whose input is somebody's claim rather than an instrument reading. It is
treated accordingly: a claim nothing else supports is passed on clearly
labelled as unconfirmed.
