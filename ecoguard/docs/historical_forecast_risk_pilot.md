# Historical Forecast-Risk Pilot

This experiment uses archived individual ECMWF IFS HRES model runs that were conservatively available before each evaluation timestamp. It does not use realized future observations as forecasts, does not modify the current-risk model, and does not create a fire probability.

## Method

[Open-Meteo Single Runs API](https://open-meteo.com/en/docs/single-runs-api) preserves each ECMWF IFS HRES run from 14 March 2024. A run is treated as available only six hours after initialization, the conservative end of Open-Meteo's documented typical 4–6 hour global-model publication delay. Forecast target values and evaluation-to-event aggregates come only from that archived run.

Forecast environmental risk signal is transparent and untrained: material worsening requires at least two of +2°C temperature, -10 percentage-point humidity, or +10 km/h wind changes from conditions available at evaluation. One is limited worsening; zero is no material worsening. Continued zero precipitation is reported as context but does not alone trigger worsening. No forecast risk score/level is produced because no forecast-trained calibration exists.

## Results

| Event | Horizon | Current risk | Forecast at event: temp / RH / wind / gust / rain | Deterioration |
|---|---:|---|---|---|
| telegram_police_362 | -12h | 0.372 MEDIUM | 32.8°C / 35% / 19.3 / 45.0 km/h / 0.0 mm | material_worsening: temperature_increase_at_least_2c;humidity_decrease_at_least_10_points;wind_increase_at_least_10_kmh;continued_no_precipitation |
| telegram_police_362 | -6h | 0.147 LOW | 32.7°C / 34% / 19.2 / 44.6 km/h / 0.0 mm | material_worsening: temperature_increase_at_least_2c;humidity_decrease_at_least_10_points;wind_increase_at_least_10_kmh;continued_no_precipitation |
| telegram_police_362 | -3h | 0.159 LOW | 32.7°C / 35% / 19.4 / 45.0 km/h / 0.0 mm | limited_worsening: temperature_increase_at_least_2c;continued_no_precipitation |
| telegram_police_4286 | -12h | 0.147 LOW | 35.3°C / 22% / 18.5 / 44.6 km/h / 0.0 mm | material_worsening: temperature_increase_at_least_2c;humidity_decrease_at_least_10_points;wind_increase_at_least_10_kmh;continued_no_precipitation |
| telegram_police_4286 | -6h | 0.112 LOW | 35.2°C / 25% / 18.1 / 43.9 km/h / 0.0 mm | material_worsening: temperature_increase_at_least_2c;humidity_decrease_at_least_10_points;wind_increase_at_least_10_kmh;continued_no_precipitation |
| telegram_police_4286 | -3h | 0.331 MEDIUM | 35.2°C / 25% / 18.1 / 43.9 km/h / 0.0 mm | no_material_worsening: continued_no_precipitation |

## Interpretation

The six rows are qualitative case studies, not accuracy or forecasting validation. Forecast signals are not probabilities and were not used to fit or select the current model, sigmoid calibration, or LOW/MEDIUM/HIGH thresholds. The event itself, later FIRMS detections, and realized post-evaluation weather are not forecast inputs.
