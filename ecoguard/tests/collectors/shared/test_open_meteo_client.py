"""The provider client: pacing, retries, rate-limit cooldown, validation.

These moved here when the rolling SQLite weather cache was deleted. They test
the client, not the cache, and the client is now the single path from the whole
system to Open-Meteo — so this is the machinery that decides whether one bad
afternoon at the provider costs us a few retries or a day of missing weather.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

from ecoguard.analyzers.fire.ml.build_historical_fire_weather_features import FEATURE_FIELDS as HISTORICAL_FIELDS
from ecoguard.analyzers.fire.ml.build_historical_fire_weather_features import compute_features as historical_compute
from ecoguard.collectors.shared.open_meteo.client import (
    HOURLY_VARIABLES, HourlyProviderError, OpenMeteoHourlyClient, validate_location_response,
)
from ecoguard.shared.weather_features import FEATURE_FIELDS, compute_features


UTC = timezone.utc
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def response(start, end, provider=(32.0, 35.0)):
    times, cursor = [], start
    while cursor <= end:
        times.append(cursor.isoformat()); cursor += timedelta(hours=1)
    hourly = {"time": times}
    for variable in HOURLY_VARIABLES:
        hourly[variable] = [float(index + 1) for index in range(len(times))]
    return {
        "provider_latitude": provider[0], "provider_longitude": provider[1],
        "provider_elevation": 100.0, "timezone": "UTC", "status": "success",
        "missing_variables": [], "hourly": hourly,
    }


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status_code, headers or {}
    def json(self): return self.payload


class OutcomeSession:
    def __init__(self, outcomes): self.outcomes, self.calls = list(outcomes), []
    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs)); outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception): raise outcome
        return outcome


class FakeClock:
    def __init__(self): self.value = 0.0; self.sleeps = []
    def monotonic(self): return self.value
    def sleep(self, seconds): self.sleeps.append(seconds); self.value += seconds


def raw_location(start=NOW - timedelta(hours=1), end=NOW):
    item = response(start, end)
    return {"latitude": item["provider_latitude"], "longitude": item["provider_longitude"],
            "elevation": 100, "timezone": "UTC", "hourly": item["hourly"]}


def test_the_live_feature_calculator_still_matches_the_training_pipeline():
    """The model was trained by the historical builder; the live path must agree.

    If these two ever diverge, the model is scored at runtime on features that
    are not the ones it learned, and nothing else in the system would notice.
    """
    event = datetime(2024, 1, 8, 12, tzinfo=UTC)
    data = response(event - timedelta(hours=168), event + timedelta(hours=2))["hourly"]
    weather = {"status": "success", "hourly": data}
    assert FEATURE_FIELDS == HISTORICAL_FIELDS
    assert compute_features(weather, event) == historical_compute(weather, event)


def test_the_window_is_requested_in_hours_not_whole_days():
    """The regression guard on an eightfold provider overcharge.

    start_date/end_date are day-granular, so a six-hour window spanning
    midnight asked for two whole calendar days — 48 hourly steps per cell to
    keep six. At 50 locations and 8 variables that is what drove the collector
    into sustained 429s.
    """
    session = OutcomeSession([FakeResponse(raw_location())])
    client = OpenMeteoHourlyClient(session=session, max_attempts=1, minimum_interval_seconds=0)
    start = datetime(2026, 8, 27, 22, tzinfo=UTC)
    end = datetime(2026, 8, 28, 1, tzinfo=UTC)

    client.fetch_range([(31.8, 35.1)], start, end)

    params = session.calls[0][1]["params"]
    assert params["start_hour"] == "2026-08-27T22:00"
    assert params["end_hour"] == "2026-08-28T01:00"
    assert "start_date" not in params and "end_date" not in params


def test_weather_code_is_collected_so_the_api_contract_can_still_be_served():
    # Nothing else fetches from Open-Meteo any more, so a variable absent here
    # is absent everywhere. weather_code is in the documented response shape.
    assert "weather_code" in HOURLY_VARIABLES


def test_provider_retries_timeout_without_logging_url():
    session = OutcomeSession([requests.Timeout(), FakeResponse(raw_location())]); logs, sleeps = [], []
    client = OpenMeteoHourlyClient(session=session, sleep=sleeps.append, retry_logger=logs.append,
                                   max_attempts=2, minimum_interval_seconds=0)
    assert len(client.fetch_range([(31.8, 35.1)], NOW - timedelta(hours=1), NOW)) == 1
    assert sleeps == [1.0] and "http" not in logs[0].lower()


def test_provider_rejects_malformed_and_mismatched_batches_without_retry():
    client = OpenMeteoHourlyClient(session=OutcomeSession([FakeResponse([raw_location()])]), max_attempts=1)
    with pytest.raises(HourlyProviderError, match="response_count_mismatch"):
        client.fetch_range([(31.8, 35.1), (31.9, 35.2)], NOW - timedelta(hours=1), NOW)
    malformed = raw_location(); malformed["hourly"]["temperature_2m"] = [1]
    with pytest.raises(HourlyProviderError, match="malformed_response"):
        validate_location_response(malformed)


def test_provider_paces_only_between_actual_http_requests_and_preserves_batching():
    clock = FakeClock()
    session = OutcomeSession([FakeResponse([raw_location(), raw_location()]), FakeResponse(raw_location())])
    client = OpenMeteoHourlyClient(
        session=session, batch_size=2, minimum_interval_seconds=15,
        sleep=clock.sleep, monotonic=clock.monotonic, max_attempts=1,
    )
    result = client.fetch_range([(31.8, 35.1), (31.9, 35.2)], NOW - timedelta(hours=1), NOW)
    assert len(result) == 2 and len(session.calls) == 1 and clock.sleeps == []
    client.fetch_range([(31.8, 35.1)], NOW - timedelta(hours=1), NOW)
    assert len(session.calls) == 2 and clock.sleeps == [15]


def test_provider_honors_retry_after_before_retrying_429():
    clock = FakeClock()
    session = OutcomeSession([FakeResponse({}, 429, {"Retry-After": "45"}), FakeResponse(raw_location())])
    client = OpenMeteoHourlyClient(
        session=session, minimum_interval_seconds=15, sleep=clock.sleep,
        monotonic=clock.monotonic, max_attempts=3,
    )
    assert len(client.fetch_range([(31.8, 35.1)], NOW - timedelta(hours=1), NOW)) == 1
    assert clock.sleeps == [45] and len(session.calls) == 2


def test_repeated_429_opens_cooldown_and_prevents_more_http_calls():
    clock = FakeClock()
    session = OutcomeSession([FakeResponse({}, 429), FakeResponse({}, 429), FakeResponse(raw_location())])
    client = OpenMeteoHourlyClient(
        session=session, minimum_interval_seconds=0, rate_limit_cooldown_seconds=60,
        max_consecutive_rate_limits=2, sleep=clock.sleep, monotonic=clock.monotonic,
    )
    with pytest.raises(HourlyProviderError, match="rate_limited"):
        client.fetch_range([(31.8, 35.1)], NOW - timedelta(hours=1), NOW)
    assert len(session.calls) == 2 and clock.sleeps == [60]
    with pytest.raises(HourlyProviderError, match="rate_limited"):
        client.fetch_range([(31.8, 35.1)], NOW - timedelta(hours=1), NOW)
    assert len(session.calls) == 2
