# Satellite heat detections

NASA's near-real-time feed of places where an instrument saw heat, with a
confidence and an intensity for each.

A detection is a warm pixel. Quarries, flares and landfills produce them on a
schedule, which is why the detector checks whether a place lights up regularly
before treating one as news.

`client.py` talks to the provider; `collector.py` stores what comes back.
