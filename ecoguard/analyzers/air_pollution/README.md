# Air pollution analyzer

Works out what a pollution reading means: how far above normal it is, how the
Ministry itself rates the air at that moment, who lives nearby, and which way
the wind would carry it.

Every answer here is calculated, not written by a model. The same readings
always produce the same assessment.

## What is here

| File | What it does |
|---|---|
| `event_analyzer.py` | Assembles the whole assessment for one episode |
| `event_qualification.py` | Decides whether an episode is worth reporting at all |
| `official_classification.py` | The Ministry's own published rating for that station |
| `additional_verification.py` | Cross-checks the reading against nearby stations |
| `population_analysis.py` | How many people the affected corridor crosses |
| `settlement_ranking.py` | Which towns lie in the way, in order |
| `transport_*.py` | Where the pollution would drift, how far, and how long it would take |
| `wind_evidence_service.py`, `ims_wind_*.py` | The wind readings the drift estimate is built on |
| `trend_inference_service.py` | Whether the reading is rising, falling or steady |
| `incident_handler.py` | The entry point the coordinator calls |

## One caution worth repeating

The drift corridor is a screening tool. A town inside it is somewhere the
pollution could reach, never somewhere anything has been measured.
