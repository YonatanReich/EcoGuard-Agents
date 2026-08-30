"""Pure, shared weather feature calculations used by historical and live data."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


FEATURE_FIELDS = (
    "temperature_1h_before", "humidity_1h_before", "wind_speed_1h_before",
    "precipitation_1h_before", "temperature_3h_before", "humidity_3h_before",
    "wind_speed_3h_before", "temperature_6h_before", "humidity_6h_before",
    "wind_speed_6h_before", "temperature_12h_before", "humidity_12h_before",
    "wind_speed_12h_before", "max_temperature_24h", "min_humidity_24h",
    "max_wind_speed_24h", "max_wind_gust_24h", "precipitation_sum_24h",
    "max_temperature_3d", "min_humidity_3d", "max_wind_speed_3d",
    "precipitation_sum_3d", "precipitation_sum_7d",
)


def _numeric(values: Iterable[Any]) -> list[float]:
    result = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            result.append(number)
    return result


def compute_features(weather: Mapping[str, Any], event_time: datetime) -> tuple[dict[str, Any], str]:
    """Preserve the historical model's strict pre-event feature semantics."""
    features = {field: None for field in FEATURE_FIELDS}
    hourly = weather.get("hourly")
    if not isinstance(hourly, Mapping) or not hourly.get("time"):
        return features, "unavailable"
    timestamps = [datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc) for value in hourly["time"]]

    def latest_at_or_before(variable: str, target: datetime) -> float | None:
        values = hourly.get(variable, [])
        matches = [
            (timestamp, values[index])
            for index, timestamp in enumerate(timestamps)
            if timestamp < event_time and timestamp <= target and index < len(values)
        ]
        if not matches:
            return None
        return (_numeric([max(matches, key=lambda item: item[0])[1]]) or [None])[0]

    lag_variables = {
        "temperature": "temperature_2m",
        "humidity": "relative_humidity_2m",
        "wind_speed": "wind_speed_10m",
    }
    for hours in (1, 3, 6, 12):
        target = event_time - timedelta(hours=hours)
        for prefix, variable in lag_variables.items():
            features[f"{prefix}_{hours}h_before"] = latest_at_or_before(variable, target)
    features["precipitation_1h_before"] = latest_at_or_before("precipitation", event_time - timedelta(hours=1))

    def window_values(variable: str, hours: int) -> list[float]:
        values = hourly.get(variable, [])
        start = event_time - timedelta(hours=hours)
        return _numeric(
            values[index]
            for index, timestamp in enumerate(timestamps)
            if start <= timestamp < event_time and index < len(values)
        )

    aggregations = (
        (24, "temperature_2m", "max_temperature_24h", max),
        (24, "relative_humidity_2m", "min_humidity_24h", min),
        (24, "wind_speed_10m", "max_wind_speed_24h", max),
        (24, "wind_gusts_10m", "max_wind_gust_24h", max),
        (24, "precipitation", "precipitation_sum_24h", sum),
        (72, "temperature_2m", "max_temperature_3d", max),
        (72, "relative_humidity_2m", "min_humidity_3d", min),
        (72, "wind_speed_10m", "max_wind_speed_3d", max),
        (72, "precipitation", "precipitation_sum_3d", sum),
        (168, "precipitation", "precipitation_sum_7d", sum),
    )
    for hours, variable, field, operation in aggregations:
        values = window_values(variable, hours)
        features[field] = operation(values) if values else None

    required = [field for field in FEATURE_FIELDS if field != "max_wind_gust_24h"]
    status = weather.get("status", "partial")
    if status == "success" and any(features[field] is None for field in required):
        status = "partial"
    if features["max_wind_gust_24h"] is None and status == "success":
        status = "partial"
    return features, str(status)
