import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from ecoguard.analyzers.fire.ml.build_historical_fire_weather_features import (
    FEATURE_FIELDS,
    HOURLY_VARIABLES,
    HistoricalWeatherError,
    OpenMeteoHistoricalClient,
    ProviderError,
    WeatherCheckpoint,
    build_historical_weather_features,
    checkpoint_configuration,
    compute_features,
    load_supported_candidates,
    parse_utc_timestamp,
    validate_hourly_response,
)


EVENT_TIME = datetime(2024, 6, 15, 10, tzinfo=timezone.utc)


def candidate(identifier="supported-1", status="supported", timestamp="2024-06-15T10:00:00Z"):
    return {
        "candidate_id": identifier,
        "start_timestamp": timestamp,
        "centroid_latitude": "31.9",
        "centroid_longitude": "34.9",
        "settlement": "רמלה",
        "settlement_lamas_code": "8500",
        "official_month_support": "true" if status == "supported" else "false",
        "official_event_count": "1",
        "firms_candidates_same_settlement_month": "2",
        "ground_truth_status": status,
    }


def write_candidates(path: Path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(candidate().keys()))
        writer.writeheader()
        writer.writerows(rows)


def hourly_weather(include_post_event=True):
    start = EVENT_TIME - timedelta(hours=168)
    count = 170 if include_post_event else 169
    timestamps = [(start + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M") for index in range(count)]
    values = list(range(count))
    if include_post_event:
        values[-1] = 9999
    hourly = {
        "time": timestamps,
        "temperature_2m": values,
        "relative_humidity_2m": [200 - value if value != 9999 else -9999 for value in values],
        "precipitation": [1] * count,
        "rain": [0.5] * count,
        "wind_speed_10m": values,
        "wind_direction_10m": [270] * count,
        "wind_gusts_10m": [value + 10 if value != 9999 else 9999 for value in values],
    }
    return {"status": "success", "hourly": hourly, "missing_variables": []}


def api_response(**overrides):
    hourly = hourly_weather()["hourly"]
    hourly.update(overrides)
    return {"timezone": "UTC", "hourly": hourly}


def test_only_supported_candidates_are_selected(tmp_path):
    path = tmp_path / "matched.csv"
    write_candidates(path, [candidate("a"), candidate("b", "unsupported"), candidate("c", "unlocated")])
    assert [row["candidate_id"] for row in load_supported_candidates(path)] == ["a"]


def test_exact_pre_event_lag_lookups():
    features, status = compute_features(hourly_weather(), EVENT_TIME)
    assert status == "success"
    assert features["temperature_1h_before"] == 167
    assert features["temperature_3h_before"] == 165
    assert features["temperature_6h_before"] == 162
    assert features["temperature_12h_before"] == 156
    assert features["humidity_1h_before"] == 33
    assert features["wind_speed_3h_before"] == 165
    assert features["precipitation_1h_before"] == 1


def test_24_hour_aggregation():
    features, _ = compute_features(hourly_weather(), EVENT_TIME)
    assert features["max_temperature_24h"] == 167
    assert features["min_humidity_24h"] == 33
    assert features["max_wind_speed_24h"] == 167
    assert features["max_wind_gust_24h"] == 177
    assert features["precipitation_sum_24h"] == 24


def test_three_day_aggregation():
    features, _ = compute_features(hourly_weather(), EVENT_TIME)
    assert features["max_temperature_3d"] == 167
    assert features["min_humidity_3d"] == 33
    assert features["max_wind_speed_3d"] == 167
    assert features["precipitation_sum_3d"] == 72


def test_seven_day_precipitation_aggregation():
    features, _ = compute_features(hourly_weather(), EVENT_TIME)
    assert features["precipitation_sum_7d"] == 168


def test_post_event_values_are_never_used():
    features, _ = compute_features(hourly_weather(include_post_event=True), EVENT_TIME)
    assert max(value for value in features.values() if value is not None) < 9999
    assert features["precipitation_sum_24h"] == 24


def test_utc_timestamp_is_required_and_provider_timezone_is_validated():
    assert parse_utc_timestamp("2024-06-15T13:00:00+03:00") == EVENT_TIME
    with pytest.raises(HistoricalWeatherError, match="UTC offset"):
        parse_utc_timestamp("2024-06-15T10:00:00")
    response = validate_hourly_response(api_response())
    assert response["status"] == "success"
    with pytest.raises(ProviderError, match="malformed response"):
        validate_hourly_response({**api_response(), "timezone": "Asia/Jerusalem"})


def test_missing_weather_rows_are_unavailable():
    response = validate_hourly_response({"timezone": "UTC", "hourly": {"time": []}})
    features, status = compute_features(response, EVENT_TIME)
    assert status == "unavailable"
    assert all(value is None for value in features.values())


def test_partial_variable_availability_keeps_available_features():
    raw = api_response()
    del raw["hourly"]["wind_gusts_10m"]
    response = validate_hourly_response(raw)
    features, status = compute_features(response, EVENT_TIME)
    assert status == "partial"
    assert features["temperature_1h_before"] == 167
    assert features["max_wind_gust_24h"] is None


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else api_response()

    def json(self):
        return self._data


class OutcomeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_transient_failure_retries_with_bounded_backoff():
    session = OutcomeSession([requests.Timeout(), FakeResponse()])
    sleeps = []
    client = OpenMeteoHistoricalClient(session=session, sleep=sleeps.append, max_attempts=3)
    result = client.fetch(31.9, 34.9, EVENT_TIME)
    assert result["status"] == "success"
    assert len(session.calls) == 2
    assert sleeps == [2.0]
    assert session.calls[0][1]["params"]["timezone"] == "UTC"
    assert session.calls[0][1]["timeout"] == 30


def test_permanent_http_failure_is_not_retried():
    session = OutcomeSession([FakeResponse(status_code=400)])
    client = OpenMeteoHistoricalClient(session=session, sleep=MagicMock())
    with pytest.raises(ProviderError, match="invalid request"):
        client.fetch(31.9, 34.9, EVENT_TIME)
    assert len(session.calls) == 1


class FakeClient:
    endpoint = "https://example.test/v1/archive"

    def __init__(self):
        self.calls = 0

    def fetch(self, latitude, longitude, event_time):
        self.calls += 1
        return hourly_weather()


def test_checkpoint_resume_skips_successful_request(tmp_path):
    input_path = tmp_path / "matched.csv"
    output_path = tmp_path / "features.csv"
    checkpoint_path = tmp_path / "checkpoint"
    write_candidates(input_path, [candidate()])
    first_client = FakeClient()
    first = build_historical_weather_features(
        input_path=input_path,
        output_path=output_path,
        checkpoint_path=checkpoint_path,
        client=first_client,
        progress_logger=lambda _: None,
        request_pause_seconds=0,
    )
    second_client = FakeClient()
    second = build_historical_weather_features(
        input_path=input_path,
        output_path=output_path,
        checkpoint_path=checkpoint_path,
        client=second_client,
        progress_logger=lambda _: None,
        request_pause_seconds=0,
    )
    assert first_client.calls == 1
    assert second_client.calls == 0
    assert first == second
    assert (checkpoint_path / "manifest.json").exists()


def test_corrupted_checkpoint_is_rejected(tmp_path):
    store = WeatherCheckpoint(tmp_path / "checkpoint", checkpoint_configuration())
    store.initialize()
    row = candidate()
    store.save(row, hourly_weather())
    path = next((tmp_path / "checkpoint" / "candidates").glob("*.json"))
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(HistoricalWeatherError, match="corrupted"):
        store.load(row)


def test_output_is_deterministic(tmp_path):
    input_path = tmp_path / "matched.csv"
    write_candidates(input_path, [candidate("b", timestamp="2024-06-16T10:00:00Z"), candidate("a")])
    first = build_historical_weather_features(
        input_path=input_path,
        output_path=tmp_path / "first.csv",
        checkpoint_path=tmp_path / "checkpoint",
        client=FakeClient(),
        progress_logger=lambda _: None,
        request_pause_seconds=0,
    )
    second = build_historical_weather_features(
        input_path=input_path,
        output_path=tmp_path / "second.csv",
        checkpoint_path=tmp_path / "checkpoint",
        client=FakeClient(),
        progress_logger=lambda _: None,
        request_pause_seconds=0,
    )
    assert first == second
    assert [row["candidate_id"] for row in first] == ["a", "b"]
    assert set(FEATURE_FIELDS).issubset(first[0])
