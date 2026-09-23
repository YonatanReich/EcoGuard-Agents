# Shared detector pieces

Things every detector needs, whatever hazard it watches.

| File | What it does |
|---|---|
| `window.py` | Decides how far back a detector reads when it has been away |

## How far back a detector looks

Each detector remembers when it last finished, and normally reads whatever has
arrived since. That is right while it runs every ten minutes, and wrong the
moment it stops — after a pause, a crash or a weekend, "since I last ran" means
two days, and reading two days of stored readings opens incidents for fires
that burned out on Tuesday.

So there is a floor. A detector reads from its own bookmark, or from the recent
past, whichever is later:

| Since it last ran | What it reads |
|---|---|
| 10 minutes | the last 10 minutes |
| 2 hours | the last 2 hours |
| 2 days | its catch-up window, and the gap is logged |
| never | its catch-up window |

The floor only bites when the gap is longer than it, so a detector on its normal
schedule is unaffected. After one catch-up run the bookmark is current again and
everything goes back to reading only new arrivals.

Skipped readings are not lost — they stay in the store, and anything that wants
history still reads them. What is skipped is treating them as news.

## How far back is "the recent past"

Three hours by default, and each detector may say otherwise where its other
windows are defined. The reason is always about its source:

| Detector | Window | Why |
|---|---|---|
| Fire, satellite | 6 h | the provider publishes about three hours behind the satellite pass |
| Fire, weather | 3 h | one missed collector tick past the point a reading goes stale |
| Flood | 3 h | the flood quiet period; older belongs to a closed episode |
| Air pollution | 3 h | forty readings per series, far more than a comparison needs |
| Earthquake | 24 h | an earthquake does not pass — last night's is still worth reporting |

`ECOGUARD_DETECTION_MAX_CATCHUP_HOURS` changes the default for detectors that
have not set their own.
