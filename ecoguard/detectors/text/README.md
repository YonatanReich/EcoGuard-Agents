# Text detector

The lane for things people write: Telegram messages and news items.

Unlike every other detector, there is no measurement here. A message is not a
reading, so the question is different: is this a report of something happening,
where, and of what kind.

| File | What it does |
|---|---|
| `classifier.py` | Asks the model what a batch of messages is reporting |
| `keywords.py` | Cheap keyword checks that run before the model is involved |
| `triage.py` | Decides whether anything else corroborates the report |
| `run.py` | Runs the lane and hands results to the coordinator |

## Corroborated and not

A report backed by an instrument - a hotspot, a gauge, a station - joins the
ordinary pipeline. A report backed by nothing is passed on tagged as
uncorroborated, and is routed to advice rather than analysis.

The model is never told which channel a message came from. Told "this is the
police", it reads the same sentence more generously, and that is exactly the
bias the source list exists to keep out of the judgement.
