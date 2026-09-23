# Daily fire-weather index

Calculated rather than fetched. The index measures how dry the fuel is and how
readily fire would spread, from weather already stored.

It needs one value per day at a midday that has fully passed, and each day
builds on the one before, so a missed day is a permanent hole and the collector
catches up in order.

`index.py` holds the published formulas; `collector.py` runs them.
