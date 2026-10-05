# detectors/fire/

Ways a fire becomes a candidate:

- `satellite.py` — **the one that sees fires.** Reads stored FIRMS hotspots,
  weighs each against how often that cell lights up anyway (`firms_baselines`),
  and emits a `CellSignal` carrying a dispatchable location, peak FRP and the
  recent growth curve. Wired to the coordinator.

  Five products feed it: three VIIRS, one MODIS, and Meteosat via the
  geostationary feed. The last is the one that matters for speed — the polar
  satellites cross a few times a day, Meteosat watches continuously and reports
  every ten minutes. On the Galilee fire of 14 September it detected at **07:08
  against VIIRS's 09:58**, and produced 114 detections to VIIRS's 13. It is
  coarser (~3 km against 375 m), so it finds fires early and VIIRS says where
  they actually are.
- `weather.py` — conditions, not events. Sweeps the stored hourly weather
  against each cell's own climatology. Wired to the coordinator as a
  corroborator: it cannot detect a fire, because the feed is a numerical model
  with no knowledge one exists.
- `telegram_candidate_filter.py` — rule-based scoring reused by the shared
  Telegram/RSS text classifier. It does not emit a `CellSignal` itself.
- `hebrew_location_extractor.py` — shared Fire/Flood location extraction via an
  offline gazetteer. The text-event lane validates its output against the
  shared towns layer before a report can become a signal.

None of these decide how dangerous the fire is.

## Which one actually detects a fire

Only `satellite.py`. This is worth stating plainly because the distinction cost
a day to learn: on 14 September a fire burned in the Galilee at 71 MW, and the
weather for that cell through the fire was an ordinary hot afternoon — humidity
*rose* from 22% to 35% as it burned. Open-Meteo is a numerical weather model
with no sensor at the location and no knowledge the fire existed, so no
threshold on it could ever have found that fire.

Weather earns its place as the corroborator and the severity input: it says
whether today is a day a fire will run. It is not, and cannot be, the thing
that notices one has started.

## Why none of them use a model

Every one of these answers **rarity**, and rarity is a lookup: where a reading
sits in this cell's own distribution for this month and hour. That number is
load-bearing arithmetic, not judgement — `REPORTING_RARITY` is a false-alarm
budget, and it only means anything if 0.999 is a real empirical percentile. A
model's estimate in that slot would leave the threshold looking identical and
quietly stop being a frequency, taking the coordinator's corroboration maths
with it.

Judgement belongs downstream, where `shared/llm.py` already serves `analyzers/`
and `response_planner/` — severity, context, what to tell people — and where it
runs once per incident rather than once per cell-hour.

The honest exception is Telegram: free Hebrew text is meaning extraction, not
statistics. The keyword filter holds for now and a missed message costs one
corroborating source, so that swap can wait until recall is the bottleneck.
