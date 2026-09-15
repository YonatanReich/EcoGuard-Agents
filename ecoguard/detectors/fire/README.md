# detectors/fire/

Three ways a fire becomes a candidate:

- `detection_agent.py` — satellite. FIRMS hotspots enriched with fire danger,
  weather and OSM context into one detected event.
- `telegram_candidate_filter.py` — social. Rule-based scoring of Hebrew channel
  messages. No network, no LLM: it flags what is worth verifying, nothing more.
- `hebrew_location_extractor.py` — turns a flagged message into coordinates via
  an offline gazetteer.

None of these decide how dangerous the fire is.
