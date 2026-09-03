# Historical pre-event weather features

This isolated dataset stage enriches only FIRMS candidates whose
`ground_truth_status` is `supported`. Here, supported means that relevant
monthly Israel Fire and Rescue records exist for the same settlement and
calendar month. It is not individual incident confirmation. Unsupported and
unlocated candidates are not negative samples and are not included in this
weather output.

## Source and request

Weather comes from the documented Open-Meteo Historical Weather API:

`https://archive-api.open-meteo.com/v1/archive`

Each request uses the FIRMS candidate centroid, not a settlement centroid. It
requests the seven preceding dates through the event date and these hourly
variables:

- `temperature_2m`
- `relative_humidity_2m`
- `precipitation`
- `rain`
- `wind_speed_10m`
- `wind_direction_10m`
- `wind_gusts_10m`

The API is explicitly requested with `timezone=UTC`, Celsius, km/h, and mm.
FIRMS `start_timestamp` values are parsed as timezone-aware timestamps and
normalized to UTC. No Israel-local timestamps are mixed into calculations.

Open-Meteo's historical endpoint is reanalysis data rather than a reading from
an incident-site weather station. Its precipitation and rain values represent
the sum during the preceding hour.

## Strict pre-event features

Only hourly records whose provider timestamp is strictly earlier than the
candidate `start_timestamp` are eligible. No post-event value is used.

For the 1, 3, 6, and 12 hour lag features, the builder selects the latest
hourly observation at or before `start_timestamp - lag`. This avoids forward
interpolation for FIRMS events that start between whole hours.

Rolling features use half-open UTC windows ending at the event:

- 24 hours: `[start_timestamp - 24h, start_timestamp)`
- 3 days: `[start_timestamp - 72h, start_timestamp)`
- 7 days: `[start_timestamp - 168h, start_timestamp)`

Temperature uses maxima, humidity uses minima, wind speed/gust uses maxima,
and precipitation uses sums. Missing variables remain empty. A response is
`partial` when some requested variables or derived features are unavailable,
`unavailable` when the provider returns no hourly rows, and `failed` for safe
provider/network error categories. Candidates are never silently dropped and
weather values are never fabricated.

## Checkpoint, resume, and retries

Validated provider responses are stored under:

`data/generated/historical_fire_weather_checkpoint/`

The manifest records the endpoint, requested variables, timezone, lookback,
and no-leakage rule. Each candidate entry contains its request identity, the
normalized hourly response, and a SHA-256 checksum. An incompatible or corrupt
checkpoint fails clearly. Successful, partial, and unavailable responses are
reused; transient failed requests remain eligible for a later retry.

Transient timeouts, network errors, HTTP 429, and HTTP 5xx responses use up to
four attempts with bounded exponential delays of 2, 4, and 8 seconds. Permanent
request errors are not retried. Errors and progress output never include full
request URLs or query parameters.

Open-Meteo supports multiple coordinates in one call. This builder deliberately
uses candidate-level requests because candidates generally have distinct
coordinates and date windows, and candidate-level checkpoints provide simple,
correct resume behavior without mixing locations. A 0.25-second pause is used
between uncached candidate requests.

Start or resume:

```console
python -m scripts.build_historical_fire_weather_features
```

The generated CSV and checkpoint directory are ignored by Git.

## Limitations

- Reanalysis values model historical atmospheric conditions; they are not
  exact incident-site instrument observations.
- Spatial resolution and model uncertainty can smooth local wind, rainfall,
  humidity, and temperature extremes.
- The FIRMS event time may occur between hourly weather timestamps.
- A supported candidate is not individually confirmed by monthly aggregate
  Fire and Rescue data.
- This stage creates no negative samples, FWI values, or ML labels.
