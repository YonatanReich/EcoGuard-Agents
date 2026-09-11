"""Build a leakage-safe archived-forecast pilot for precise Tier B events."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

TRAJECTORY_INPUT = Path("data/generated/fire_risk_strong_event_trajectory_results.csv")
OUTPUT_PATH = Path("data/generated/historical_forecast_risk_pilot.csv")
CACHE_PATH = Path("data/generated/historical_forecast_risk_pilot_cache")
REPORT_PATH = Path("docs/historical_forecast_risk_pilot.md")
ENDPOINT = "https://single-runs-api.open-meteo.com/v1/forecast"
MODEL = "ecmwf_ifs"
MODEL_DESCRIPTION = "ECMWF IFS HRES archived individual run via Open-Meteo Single Runs API"
MODEL_AVAILABILITY_DELAY_HOURS = 6
TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 3
VARIABLES = ("temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m", "wind_gusts_10m")
HORIZONS = (-12, -6, -3)


class ForecastPilotError(RuntimeError):
    pass


def parse_utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ForecastPilotError("timestamp is malformed") from None
    if parsed.tzinfo is None:
        raise ForecastPilotError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def select_available_run(evaluation_time: datetime, availability_delay_hours: int = MODEL_AVAILABILITY_DELAY_HOURS) -> datetime:
    """Latest six-hour ECMWF cycle conservatively available by evaluation time."""
    available_initialization = evaluation_time - timedelta(hours=availability_delay_hours)
    cycle_hour = max(hour for hour in (0, 6, 12, 18) if hour <= available_initialization.hour)
    return available_initialization.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)


class SingleRunForecastClient:
    def __init__(self, session: Any | None = None, sleep: Callable[[float], None] = time.sleep):
        self.session = session or requests.Session()
        self.sleep = sleep

    def fetch(self, latitude: float, longitude: float, run_time: datetime) -> dict[str, Any]:
        params = {
            "latitude": latitude, "longitude": longitude,
            "run": run_time.strftime("%Y-%m-%dT%H:%M"), "hourly": ",".join(VARIABLES),
            "models": MODEL, "timezone": "UTC", "wind_speed_unit": "kmh", "forecast_days": 2,
        }
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.session.get(
                    ENDPOINT, params=params,
                    headers={"User-Agent": "EcoGuard-Agents historical-forecast-risk-pilot/1.0", "Accept": "application/json"},
                    timeout=TIMEOUT_SECONDS,
                )
                if response.status_code in {400, 401, 403, 404}:
                    raise ForecastPilotError(f"forecast provider permanent HTTP {response.status_code}")
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.RequestException("transient provider failure")
                data = response.json()
                return validate_forecast(data, run_time)
            except (requests.Timeout, requests.RequestException, ValueError):
                if attempt == MAX_ATTEMPTS:
                    raise ForecastPilotError("forecast provider network or malformed-response failure") from None
                self.sleep(2 ** (attempt - 1))
        raise AssertionError("unreachable")


def validate_forecast(data: Any, run_time: datetime) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("timezone") not in {"GMT", "UTC"} or not isinstance(data.get("hourly"), dict):
        raise ForecastPilotError("forecast response is malformed")
    hourly = data["hourly"]
    timestamps = hourly.get("time")
    if not isinstance(timestamps, list) or not timestamps:
        raise ForecastPilotError("forecast response has no timestamps")
    parsed = [datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc) for value in timestamps]
    if parsed[0] < run_time:
        raise ForecastPilotError("forecast precedes selected model run")
    for variable in VARIABLES:
        if not isinstance(hourly.get(variable), list) or len(hourly[variable]) != len(parsed):
            raise ForecastPilotError(f"forecast response is missing {variable}")
    return {"run_time": run_time.isoformat(), "hourly": hourly}


def _cache_file(event_id: str, horizon: int, run_time: datetime, cache_path: Path) -> Path:
    identity = f"{event_id}|{horizon}|{run_time.isoformat()}|{MODEL}"
    return cache_path / f"{hashlib.sha256(identity.encode()).hexdigest()[:32]}.json"


def cached_forecast(event: Mapping[str, Any], client: SingleRunForecastClient, cache_path: Path = CACHE_PATH) -> tuple[dict[str, Any], bool]:
    evaluation = parse_utc(event["evaluation_reference_time"])
    run_time = select_available_run(evaluation)
    path = _cache_file(event["original_event_id"], int(event["trajectory_offset_hours"]), run_time, cache_path)
    if path.exists():
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            payload = envelope["payload"]
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if envelope.get("sha256") != digest or payload.get("run_time") != run_time.isoformat():
                raise ValueError
            return payload, True
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            raise ForecastPilotError("forecast cache entry is corrupted") from None
    payload = client.fetch(float(event["latitude"]), float(event["longitude"]), run_time)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    envelope = {"sha256": hashlib.sha256(canonical.encode()).hexdigest(), "payload": payload}
    cache_path.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
    return payload, False


def forecast_indicators(forecast: Mapping[str, Any], evaluation_time: datetime, event_time: datetime) -> dict[str, Any]:
    if not evaluation_time < event_time:
        raise ForecastPilotError("forecast target must be after evaluation time")
    hourly = forecast["hourly"]
    timestamps = [datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc) for value in hourly["time"]]
    target_index = min(
        (index for index, timestamp in enumerate(timestamps) if timestamp <= event_time),
        key=lambda index: abs((timestamps[index] - event_time).total_seconds()),
        default=None,
    )
    if target_index is None or timestamps[target_index] < event_time - timedelta(hours=1):
        raise ForecastPilotError("forecast does not cover event target time")
    window = [index for index, timestamp in enumerate(timestamps) if evaluation_time < timestamp <= event_time]
    if not window:
        raise ForecastPilotError("forecast has no future event window")
    numeric = lambda variable, indices: [float(hourly[variable][index]) for index in indices if hourly[variable][index] is not None and math.isfinite(float(hourly[variable][index]))]
    target = lambda variable: float(hourly[variable][target_index]) if hourly[variable][target_index] is not None else None
    return {
        "forecast_target_time": timestamps[target_index].isoformat(),
        "forecast_temperature_event": target("temperature_2m"),
        "forecast_humidity_event": target("relative_humidity_2m"),
        "forecast_wind_speed_event": target("wind_speed_10m"),
        "forecast_wind_gust_event": target("wind_gusts_10m"),
        "forecast_precipitation_event": target("precipitation"),
        "forecast_max_temperature_to_event": max(numeric("temperature_2m", window)),
        "forecast_min_humidity_to_event": min(numeric("relative_humidity_2m", window)),
        "forecast_max_wind_speed_to_event": max(numeric("wind_speed_10m", window)),
        "forecast_max_wind_gust_to_event": max(numeric("wind_gusts_10m", window)),
        "forecast_precipitation_sum_to_event": sum(numeric("precipitation", window)),
    }


def deterioration(current: Mapping[str, Any], forecast: Mapping[str, Any]) -> dict[str, Any]:
    temperature_change = float(forecast["forecast_temperature_event"]) - float(current["temperature_1h_before"])
    humidity_change = float(forecast["forecast_humidity_event"]) - float(current["humidity_1h_before"])
    wind_change = float(forecast["forecast_wind_speed_event"]) - float(current["wind_speed_1h_before"])
    flags = []
    if temperature_change >= 2.0: flags.append("temperature_increase_at_least_2c")
    if humidity_change <= -10.0: flags.append("humidity_decrease_at_least_10_points")
    if wind_change >= 10.0: flags.append("wind_increase_at_least_10_kmh")
    dry = float(forecast["forecast_precipitation_sum_to_event"]) == 0.0 and float(current["precipitation_1h_before"]) == 0.0
    if dry: flags.append("continued_no_precipitation")
    hazardous_changes = sum(flag != "continued_no_precipitation" for flag in flags)
    signal = "material_worsening" if hazardous_changes >= 2 else "limited_worsening" if hazardous_changes == 1 else "no_material_worsening"
    return {
        "forecast_temperature_change_c": round(temperature_change, 3),
        "forecast_humidity_change_percentage_points": round(humidity_change, 3),
        "forecast_wind_speed_change_kmh": round(wind_change, 3),
        "forecast_deterioration_flags": ";".join(flags),
        "forecast_environmental_risk_signal": signal,
        "forecast_risk_score": "", "forecast_risk_level": "",
        "forecast_risk_status": "not_calculated_no_forecast_trained_or_calibrated_model",
    }


def load_pilot_rows(path: Path = TRAJECTORY_INPUT) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    event_times = {
        row["original_event_id"]: row["evaluation_reference_time"]
        for row in rows
        if row.get("source_type") == "verified_telegram" and int(row.get("trajectory_offset_hours", 0)) == 0
    }
    selected = []
    for row in rows:
        if row.get("source_type") != "verified_telegram" or int(row.get("trajectory_offset_hours", 0)) not in HORIZONS:
            continue
        event_time = event_times.get(row["original_event_id"])
        if not event_time:
            raise ForecastPilotError("precise event has no retained T0 reference row")
        selected.append({**row, "actual_event_timestamp": event_time})
    return sorted(selected, key=lambda row: (row["original_event_id"], int(row["trajectory_offset_hours"])))


def build_rows(rows: list[Mapping[str, Any]], client: SingleRunForecastClient, cache_path: Path = CACHE_PATH) -> list[dict[str, Any]]:
    event_times = {row["original_event_id"]: parse_utc(row["actual_event_timestamp"]) for row in rows}
    output = []
    for row in rows:
        evaluation = parse_utc(row["evaluation_reference_time"])
        event_time = event_times[row["original_event_id"]]
        payload, cache_hit = cached_forecast(row, client, cache_path)
        run_time = parse_utc(payload["run_time"])
        available_at = run_time + timedelta(hours=MODEL_AVAILABILITY_DELAY_HOURS)
        if available_at > evaluation:
            raise ForecastPilotError("selected forecast run was not conservatively available at evaluation time")
        forecast = forecast_indicators(payload, evaluation, event_time)
        output.append({
            "event_id": row["original_event_id"], "event_timestamp": event_time.isoformat(),
            "event_location": row["location"], "horizon_hours": int(row["trajectory_offset_hours"]),
            "evaluation_time": evaluation.isoformat(), "current_risk_score": row["risk_score"],
            "current_risk_level": row["risk_level"], "forecast_source": MODEL_DESCRIPTION,
            "forecast_model_run_initialization": run_time.isoformat(), "forecast_conservative_available_at": available_at.isoformat(),
            "forecast_cache_hit": str(cache_hit).lower(), **forecast, **deterioration(row, forecast),
        })
    return output


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def write_report(path: Path, rows: list[Mapping[str, Any]]) -> None:
    lines = [
        "# Historical Forecast-Risk Pilot", "",
        "This experiment uses archived individual ECMWF IFS HRES model runs that were conservatively available before each evaluation timestamp. It does not use realized future observations as forecasts, does not modify the current-risk model, and does not create a fire probability.", "",
        "## Method", "",
        "[Open-Meteo Single Runs API](https://open-meteo.com/en/docs/single-runs-api) preserves each ECMWF IFS HRES run from 14 March 2024. A run is treated as available only six hours after initialization, the conservative end of Open-Meteo's documented typical 4–6 hour global-model publication delay. Forecast target values and evaluation-to-event aggregates come only from that archived run.", "",
        "Forecast environmental risk signal is transparent and untrained: material worsening requires at least two of +2°C temperature, -10 percentage-point humidity, or +10 km/h wind changes from conditions available at evaluation. One is limited worsening; zero is no material worsening. Continued zero precipitation is reported as context but does not alone trigger worsening. No forecast risk score/level is produced because no forecast-trained calibration exists.", "",
        "## Results", "",
        "| Event | Horizon | Current risk | Forecast at event: temp / RH / wind / gust / rain | Deterioration |", "|---|---:|---|---|---|",
    ]
    for row in rows:
        weather = f"{float(row['forecast_temperature_event']):.1f}°C / {float(row['forecast_humidity_event']):.0f}% / {float(row['forecast_wind_speed_event']):.1f} / {float(row['forecast_wind_gust_event']):.1f} km/h / {float(row['forecast_precipitation_event']):.1f} mm"
        lines.append(f"| {row['event_id']} | {row['horizon_hours']}h | {float(row['current_risk_score']):.3f} {str(row['current_risk_level']).upper()} | {weather} | {row['forecast_environmental_risk_signal']}: {row['forecast_deterioration_flags'] or 'none'} |")
    lines.extend(["", "## Interpretation", "", "The six rows are qualitative case studies, not accuracy or forecasting validation. Forecast signals are not probabilities and were not used to fit or select the current model, sigmoid calibration, or LOW/MEDIUM/HIGH thresholds. The event itself, later FIRMS detections, and realized post-evaluation weather are not forecast inputs.", ""])
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8"); temporary.replace(path)


def build(client: SingleRunForecastClient | None = None) -> list[dict[str, Any]]:
    rows = build_rows(load_pilot_rows(), client or SingleRunForecastClient())
    _write_csv(OUTPUT_PATH, rows); write_report(REPORT_PATH, rows)
    return rows


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try: rows = build()
    except (ForecastPilotError, OSError) as error:
        print(f"Historical forecast-risk pilot failed: {error}"); return 1
    print(f"Historical forecast-risk pilot rows: {len(rows)}"); return 0


if __name__ == "__main__": raise SystemExit(main())
