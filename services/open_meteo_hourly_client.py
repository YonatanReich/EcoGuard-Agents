"""Batched, injectable Open-Meteo hourly client for the rolling weather cache."""

from __future__ import annotations

import math
import time
from email.utils import parsedate_to_datetime
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import requests


FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
# The fire-risk model uses the first seven. weather_code is collected because
# /api/environmental-data promises it in the documented contract and the
# reasoning agents read it as context — once this is the only path to
# Open-Meteo, anything not collected here is simply unavailable.
HOURLY_VARIABLES = (
    "temperature_2m", "relative_humidity_2m", "precipitation", "rain",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "weather_code",
)
DEFAULT_BATCH_SIZE = 50
DEFAULT_MINIMUM_INTERVAL_SECONDS = 15.0
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60.0
DEFAULT_MAX_CONSECUTIVE_RATE_LIMITS = 2


class HourlyProviderError(RuntimeError):
    def __init__(self, category: str, *, transient: bool):
        super().__init__(category)
        self.category = category
        self.transient = transient


def _hour_param(value: datetime) -> str:
    """Format a timestamp for Open-Meteo's start_hour/end_hour, in UTC.

    Naive input is read as UTC rather than rejected: every caller in this
    repository works in UTC, and the request already pins timezone=UTC, so
    guessing local time here would be the only way to get it wrong.
    """
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")


def _utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise HourlyProviderError("malformed_response", transient=False) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_location_response(data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping) or data.get("timezone") not in {"UTC", "GMT"}:
        raise HourlyProviderError("malformed_response", transient=False)
    try:
        latitude, longitude = float(data["latitude"]), float(data["longitude"])
    except (KeyError, TypeError, ValueError):
        raise HourlyProviderError("malformed_response", transient=False) from None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise HourlyProviderError("malformed_response", transient=False)
    hourly = data.get("hourly")
    if not isinstance(hourly, Mapping) or not isinstance(hourly.get("time"), list):
        raise HourlyProviderError("malformed_response", transient=False)
    size = len(hourly["time"])
    timestamps = [_utc(value) for value in hourly["time"]]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise HourlyProviderError("malformed_response", transient=False)
    normalized: dict[str, list[Any]] = {"time": [value.isoformat() for value in timestamps]}
    missing = []
    for variable in HOURLY_VARIABLES:
        values = hourly.get(variable)
        if not isinstance(values, list) or len(values) != size:
            raise HourlyProviderError("malformed_response", transient=False)
        clean = []
        for value in values:
            if value is None:
                clean.append(None)
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise HourlyProviderError("malformed_response", transient=False) from None
            if not math.isfinite(number):
                raise HourlyProviderError("malformed_response", transient=False)
            clean.append(number)
        if all(value is None for value in clean):
            missing.append(variable)
        normalized[variable] = clean
    return {
        "provider_latitude": latitude,
        "provider_longitude": longitude,
        "provider_elevation": data.get("elevation"),
        "timezone": "UTC",
        "status": "partial" if missing else "success",
        "missing_variables": missing,
        "hourly": normalized,
    }


class OpenMeteoHourlyClient:
    def __init__(
        self, *, endpoint: str = FORECAST_ENDPOINT, session: Any | None = None,
        timeout: float = 30.0, batch_size: int = DEFAULT_BATCH_SIZE,
        max_attempts: int = 4, sleep: Callable[[float], None] = time.sleep,
        retry_logger: Callable[[str], None] = print,
        minimum_interval_seconds: float = DEFAULT_MINIMUM_INTERVAL_SECONDS,
        rate_limit_cooldown_seconds: float = DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS,
        max_consecutive_rate_limits: int = DEFAULT_MAX_CONSECUTIVE_RATE_LIMITS,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if batch_size < 1 or minimum_interval_seconds < 0 or rate_limit_cooldown_seconds < 0:
            raise ValueError("batch size must be positive and timing values non-negative")
        if max_consecutive_rate_limits < 1:
            raise ValueError("max_consecutive_rate_limits must be positive")
        self.endpoint, self.session, self.timeout = endpoint, session or requests.Session(), timeout
        self.batch_size, self.max_attempts = batch_size, max_attempts
        self.sleep, self.retry_logger = sleep, retry_logger
        self.minimum_interval_seconds = minimum_interval_seconds
        self.rate_limit_cooldown_seconds = rate_limit_cooldown_seconds
        self.max_consecutive_rate_limits = max_consecutive_rate_limits
        self.monotonic, self.wall_clock = monotonic, wall_clock
        self.request_count = 0
        self._last_request_at: float | None = None
        self._cooldown_until = 0.0
        self._consecutive_rate_limits = 0

    def _before_http_request(self) -> None:
        now = self.monotonic()
        if now < self._cooldown_until:
            raise HourlyProviderError("rate_limited", transient=True)
        if self._last_request_at is not None:
            delay = self.minimum_interval_seconds - (now - self._last_request_at)
            if delay > 0:
                self.sleep(delay)
        self._last_request_at = self.monotonic()

    def _retry_after_seconds(self, response: Any) -> float | None:
        value = getattr(response, "headers", {}).get("Retry-After")
        if value is None:
            return None
        try:
            seconds = float(value)
            return seconds if math.isfinite(seconds) and seconds >= 0 else None
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(str(value))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0.0, (parsed.astimezone(timezone.utc) - self.wall_clock()).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    def fetch_range(
        self, coordinates: Sequence[tuple[float, float]], start: datetime, end: datetime,
    ) -> list[dict[str, Any]]:
        if not coordinates or len(coordinates) > self.batch_size or start > end:
            raise ValueError("invalid coordinate batch or time range")
        # start_hour/end_hour, not start_date/end_date. The date form is
        # day-granular, so asking for the last six hours across midnight
        # downloaded two whole calendar days — 48 hourly steps per cell to keep
        # six. At 7 variables x 50 locations that is an eightfold overcharge
        # against Open-Meteo's per-call weighting, and it is what put the
        # collector into sustained 429s. The hour form asks for exactly the
        # window the caller wants.
        params = {
            "latitude": ",".join(str(float(value[0])) for value in coordinates),
            "longitude": ",".join(str(float(value[1])) for value in coordinates),
            "start_hour": _hour_param(start), "end_hour": _hour_param(end),
            "hourly": ",".join(HOURLY_VARIABLES), "timezone": "UTC",
            "temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm",
        }
        for attempt in range(1, self.max_attempts + 1):
            retry_after: float | None = None
            self._before_http_request()
            self.request_count += 1
            try:
                response = self.session.get(
                    self.endpoint, params=params,
                    headers={"User-Agent": "EcoGuard-Agents rolling-weather-cache/1.0", "Accept": "application/json"},
                    timeout=self.timeout,
                )
                status = int(response.status_code)
                if status >= 400:
                    transient = status == 429 or status >= 500
                    category = "rate_limited" if status == 429 else "provider_http_error" if transient else "invalid_request"
                    if status == 429:
                        self._consecutive_rate_limits += 1
                        retry_after = self._retry_after_seconds(response)
                        cooldown = max(
                            self.rate_limit_cooldown_seconds if retry_after is None else retry_after,
                            2.0 ** (attempt - 1),
                        )
                        if self._consecutive_rate_limits >= self.max_consecutive_rate_limits:
                            self._cooldown_until = self.monotonic() + cooldown
                            # Stop this batch immediately. Further calls on this client
                            # fail at the cooldown guard without touching the provider.
                            raise HourlyProviderError(category, transient=False)
                    raise HourlyProviderError(category, transient=transient)
                try:
                    payload = response.json()
                except (TypeError, ValueError):
                    raise HourlyProviderError("malformed_response", transient=False) from None
                items = [payload] if len(coordinates) == 1 and isinstance(payload, Mapping) else payload
                if not isinstance(items, list) or len(items) != len(coordinates):
                    raise HourlyProviderError("response_count_mismatch", transient=False)
                validated = [validate_location_response(item) for item in items]
                self._consecutive_rate_limits = 0
                return validated
            except requests.Timeout:
                error = HourlyProviderError("timeout", transient=True)
            except requests.RequestException:
                error = HourlyProviderError("network_error", transient=True)
            except HourlyProviderError as caught:
                error = caught
            if not error.transient or attempt == self.max_attempts:
                raise error
            delay = retry_after if retry_after is not None else (
                self.rate_limit_cooldown_seconds if error.category == "rate_limited" else min(30.0, 2.0 ** (attempt - 1))
            )
            delay = max(delay, 2.0 ** (attempt - 1))
            self.retry_logger(f"Weather batch retry: attempt={attempt + 1}/{self.max_attempts}; reason={error.category}; delay={delay:.1f}s")
            self.sleep(delay)
        raise AssertionError("unreachable")
