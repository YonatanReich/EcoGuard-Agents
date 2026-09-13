# shared/

Things more than one stage reads. The rule is the same as
`collection/shared/`: **the test is dependency, not subject matter.** If only
one stage ever imports it, it belongs in that stage's folder even when it
sounds general.

- `llm.py`, `protocols.py`, `schemas.py` — analysis, planning and the judge all
  use these.
- `grid.py`, `service_area.py` — collection *and* analysis define the country
  and its 5 km cells through these.
- `weather_features.py` — the seam contract between what collection stores and
  what analysis computes.
- `geospatial_context.py` — detection and resource allocation both need OSM
  context.
- `weather_reader.py`, `geocoding.py`, `locations.py`.
