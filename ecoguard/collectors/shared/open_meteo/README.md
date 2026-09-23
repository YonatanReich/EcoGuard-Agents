# Weather

The only thing in the system that talks to the weather provider. Everything
else reads what this wrote.

| File | What it does |
|---|---|
| `client.py` | Talks to the provider, and respects its rate limit |
| `observations.py` | The hours of weather each cell is still missing |
| `forecast.py` | Two days of forecast per cell, for lead time |

Observations are asked for by the hour, and only the hours that are absent, so
a tick with nothing to collect makes no requests at all.
