from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
import requests

from scripts.build_historical_fire_weather_features import FEATURE_FIELDS as HISTORICAL_FIELDS
from scripts.build_historical_fire_weather_features import compute_features as historical_compute
from services.open_meteo_hourly_client import (
    HOURLY_VARIABLES, HourlyProviderError, OpenMeteoHourlyClient, validate_location_response,
)
from services.rolling_weather_cache import (
    SOURCE_KIND, RollingWeatherCache, WeatherCacheError, missing_hour_ranges, weather_node_id,
)
from services.weather_feature_calculator import FEATURE_FIELDS, compute_features


UTC = timezone.utc
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def make_grid(path, cells=(("a", 31.8, 35.1, 1), ("b", 31.81, 35.11, 1))):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE risk_grid_cells(cell_id TEXT PRIMARY KEY,latitude REAL,longitude REAL,active INTEGER)")
    connection.executemany("INSERT INTO risk_grid_cells VALUES(?,?,?,?)", cells)
    connection.commit(); connection.close()


def make_service_area(path, west=34.0, south=29.0, east=36.0, north=34.0):
    path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":'
        f'{{"type":"Polygon","coordinates":[[[{west},{south}],[{east},{south}],[{east},{north}],'
        f'[{west},{north}],[{west},{south}]]]}}}}]}}', encoding="utf-8",
    )
    return path


def response(start, end, provider=(32.0, 35.0), extra_future=False):
    times, cursor = [], start
    while cursor <= end:
        times.append(cursor.isoformat()); cursor += timedelta(hours=1)
    if extra_future:
        times.append((end + timedelta(hours=3)).isoformat())
    hourly = {"time": times}
    for variable in HOURLY_VARIABLES:
        hourly[variable] = [float(index + 1) for index in range(len(times))]
    return {
        "provider_latitude": provider[0], "provider_longitude": provider[1],
        "provider_elevation": 100.0, "timezone": "UTC", "status": "success",
        "missing_variables": [], "hourly": hourly,
    }


class FakeClient:
    def __init__(self, *, provider=(32.0, 35.0), batch_size=50, fail_calls=()):
        self.provider, self.batch_size = provider, batch_size
        self.fail_calls, self.calls = set(fail_calls), []

    def fetch_range(self, coordinates, start, end):
        self.calls.append((list(coordinates), start, end))
        if len(self.calls) in self.fail_calls:
            raise HourlyProviderError("timeout", transient=True)
        return [response(start, end, self.provider) for _ in coordinates]


def test_shared_feature_calculator_is_exact_historical_compatibility():
    event = datetime(2024, 1, 8, 12, tzinfo=UTC)
    data = response(event - timedelta(hours=168), event + timedelta(hours=2))["hourly"]
    weather = {"status": "success", "hourly": data}
    assert FEATURE_FIELDS == HISTORICAL_FIELDS
    assert compute_features(weather, event) == historical_compute(weather, event)


def test_missing_ranges_include_interior_gaps():
    start = NOW - timedelta(hours=4); end = NOW
    existing = [start, start + timedelta(hours=2), end]
    assert missing_hour_ranges(existing, start, end) == [
        (start + timedelta(hours=1), start + timedelta(hours=1)),
        (start + timedelta(hours=3), start + timedelta(hours=3)),
    ]


def test_bootstrap_node_reuse_and_second_run_has_no_acquisition(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"
    make_grid(grid)
    cache, first = RollingWeatherCache(path), FakeClient()
    result = cache.update(grid_path=grid, client=first, now=NOW)
    assert result["active_grid_cells"] == 2
    assert result["unique_weather_nodes"] == 1
    assert result["reuse_ratio"] == 2.0
    assert result["inserted_hours"] == 216
    second = FakeClient()
    result2 = cache.update(grid_path=grid, client=second, now=NOW)
    assert second.calls == []
    assert result2["cache_hits"] == 1
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM grid_weather_nodes").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM hourly_weather").fetchone()[0] == 216
    connection.close()


def test_inactive_grid_cells_are_not_mapped_or_requested(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"
    make_grid(grid, (("active", 31.8, 35.1, 1), ("inactive", 31.9, 35.2, 0)))
    client = FakeClient()
    RollingWeatherCache(path).update(grid_path=grid, client=client, now=NOW)
    assert len(client.calls[0][0]) == 1
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT cell_id FROM grid_weather_nodes").fetchall() == [("active",)]
    connection.close()


def test_incompatible_cache_configuration_is_rejected(tmp_path):
    path = tmp_path / "weather.sqlite"
    RollingWeatherCache(path, retention_hours=216).initialize()
    with pytest.raises(WeatherCacheError, match="configuration is incompatible"):
        RollingWeatherCache(path, retention_hours=200).initialize()


def test_only_new_hour_is_fetched_and_duplicate_hours_are_impossible(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"; make_grid(grid, (("a", 31.8, 35.1, 1),))
    cache = RollingWeatherCache(path); cache.update(grid_path=grid, client=FakeClient(), now=NOW)
    client = FakeClient(); result = cache.update(grid_path=grid, client=client, now=NOW + timedelta(hours=1))
    assert len(client.calls) == 1
    assert client.calls[0][1] == client.calls[0][2] == NOW
    assert result["inserted_hours"] == 1
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM hourly_weather").fetchone()[0] == 216
    connection.close()


def test_interior_gap_is_repaired(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"; make_grid(grid, (("a", 31.8, 35.1, 1),))
    cache = RollingWeatherCache(path); cache.update(grid_path=grid, client=FakeClient(), now=NOW)
    missing = NOW - timedelta(hours=50)
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM hourly_weather WHERE valid_time_utc=?", (missing.isoformat().replace("+00:00", "Z"),)); connection.commit(); connection.close()
    client = FakeClient(); result = cache.update(grid_path=grid, client=client, now=NOW)
    assert len(client.calls) == 1 and client.calls[0][1] == client.calls[0][2] == missing
    assert result["stale_nodes"] == 0


def test_partial_failure_preserves_existing_rows_and_is_resumable(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"; make_grid(grid, (("a", 31.8, 35.1, 1),))
    cache = RollingWeatherCache(path); cache.update(grid_path=grid, client=FakeClient(), now=NOW)
    failed = cache.update(grid_path=grid, client=FakeClient(fail_calls={1}), now=NOW + timedelta(hours=1))
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM hourly_weather").fetchone()[0] == 216
    connection.close()
    assert failed["status"] == "partial" and failed["stale_nodes"] == 1
    resumed = cache.update(grid_path=grid, client=FakeClient(), now=NOW + timedelta(hours=1))
    assert resumed["status"] == "success"


def test_retention_prunes_only_after_successful_refresh(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"; make_grid(grid, (("a", 31.8, 35.1, 1),))
    cache = RollingWeatherCache(path); cache.update(grid_path=grid, client=FakeClient(), now=NOW)
    node = weather_node_id(32.0, 35.0); old = NOW - timedelta(hours=400)
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO hourly_weather VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (node, old.isoformat().replace("+00:00", "Z"), 1, 1, 0, 0, 1, 1, 1, SOURCE_KIND, "test", NOW.isoformat(), "success"),
    ); connection.commit(); connection.close()
    cache.update(grid_path=grid, client=FakeClient(fail_calls={1}), now=NOW + timedelta(hours=1))
    connection = sqlite3.connect(path); assert connection.execute("SELECT COUNT(*) FROM hourly_weather WHERE valid_time_utc=?", (old.isoformat().replace("+00:00", "Z"),)).fetchone()[0] == 1; connection.close()
    cache.update(grid_path=grid, client=FakeClient(), now=NOW + timedelta(hours=1))
    connection = sqlite3.connect(path); assert connection.execute("SELECT COUNT(*) FROM hourly_weather WHERE valid_time_utc=?", (old.isoformat().replace("+00:00", "Z"),)).fetchone()[0] == 0; connection.close()


def test_feature_read_never_uses_future_rows(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"; make_grid(grid, (("a", 31.8, 35.1, 1),))
    cache = RollingWeatherCache(path); cache.update(grid_path=grid, client=FakeClient(), now=NOW)
    node = weather_node_id(32.0, 35.0)
    connection = sqlite3.connect(path)
    future = NOW + timedelta(hours=2)
    connection.execute("INSERT INTO hourly_weather VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (node, future.isoformat().replace("+00:00", "Z"), 9999, 9999, 9999, 9999, 9999, 9999, 9999, SOURCE_KIND, "test", NOW.isoformat(), "success")); connection.commit(); connection.close()
    result = cache.features_for_cell("a", NOW)
    assert result["features"]["max_temperature_24h"] < 9999
    assert result["features"]["max_wind_gust_24h"] < 9999


def test_feature_read_reports_stale_when_required_hour_is_missing(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"; make_grid(grid, (("a", 31.8, 35.1, 1),))
    cache = RollingWeatherCache(path); cache.update(grid_path=grid, client=FakeClient(), now=NOW)
    missing = NOW - timedelta(hours=24)
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM hourly_weather WHERE valid_time_utc=?", (missing.isoformat().replace("+00:00", "Z"),))
    connection.commit(); connection.close()
    result = cache.features_for_cell("a", NOW)
    assert result["status"] == "stale"
    assert result["reason"] == "weather_history_incomplete"
    assert result["missing_hours"] == 1


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


def raw_location(start=NOW - timedelta(hours=1), end=NOW):
    item = response(start, end)
    return {"latitude": item["provider_latitude"], "longitude": item["provider_longitude"], "elevation": 100, "timezone": "UTC", "hourly": item["hourly"]}


def test_provider_retries_timeout_without_logging_url():
    session = OutcomeSession([requests.Timeout(), FakeResponse(raw_location())]); logs, sleeps = [], []
    client = OpenMeteoHourlyClient(session=session, sleep=sleeps.append, retry_logger=logs.append, max_attempts=2, minimum_interval_seconds=0)
    assert len(client.fetch_range([(31.8, 35.1)], NOW - timedelta(hours=1), NOW)) == 1
    assert sleeps == [1.0] and "http" not in logs[0].lower()


def test_provider_rejects_malformed_and_mismatched_batches_without_retry():
    client = OpenMeteoHourlyClient(session=OutcomeSession([FakeResponse([raw_location()])]), max_attempts=1)
    with pytest.raises(HourlyProviderError, match="response_count_mismatch"):
        client.fetch_range([(31.8, 35.1), (31.9, 35.2)], NOW - timedelta(hours=1), NOW)
    malformed = raw_location(); malformed["hourly"]["temperature_2m"] = [1]
    with pytest.raises(HourlyProviderError, match="malformed_response"):
        validate_location_response(malformed)


def test_service_area_filters_before_network_and_includes_boundary(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"
    make_grid(grid, (("inside", 31.0, 35.0, 1), ("boundary", 31.0, 35.5, 1),
                     ("overlap", 31.0, 35.51, 1), ("outside", 31.0, 35.6, 1)))
    client = FakeClient()
    result = RollingWeatherCache(path).update(
        grid_path=grid, client=client, now=NOW,
        service_area_path=make_service_area(tmp_path / "area.geojson", 34.5, 30.5, 35.5, 31.5),
    )
    assert [coordinate for coordinate in client.calls[0][0]] == [(31.0, 35.0), (31.0, 35.5), (31.0, 35.51)]
    assert result["active_grid_cells_before_service_area"] == 4
    assert result["active_grid_cells"] == 3 and result["service_area_excluded_cells"] == 1


def test_excluded_mappings_and_rows_remain_while_shared_in_service_node_refreshes(tmp_path):
    grid, path = tmp_path / "grid.sqlite", tmp_path / "weather.sqlite"
    make_grid(grid, (("inside", 31.0, 35.0, 1), ("outside", 31.0, 35.6, 1)))
    cache = RollingWeatherCache(path)
    broad = make_service_area(tmp_path / "broad.geojson")
    cache.update(grid_path=grid, client=FakeClient(), now=NOW, service_area_path=broad)
    connection = sqlite3.connect(path)
    mappings_before = connection.execute("SELECT COUNT(*) FROM grid_weather_nodes").fetchone()[0]
    rows_before = connection.execute("SELECT COUNT(*) FROM hourly_weather").fetchone()[0]
    connection.close()

    client = FakeClient()
    result = cache.update(
        grid_path=grid, client=client, now=NOW + timedelta(hours=1),
        service_area_path=make_service_area(tmp_path / "narrow.geojson", 34.5, 30.5, 35.5, 31.5),
    )
    assert len(client.calls) == 1 and len(client.calls[0][0]) == 1
    assert result["unique_weather_nodes"] == 1
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM grid_weather_nodes").fetchone()[0] == mappings_before == 2
    assert connection.execute("SELECT COUNT(*) FROM hourly_weather").fetchone()[0] == rows_before
    connection.close()


class FakeClock:
    def __init__(self): self.value = 0.0; self.sleeps = []
    def monotonic(self): return self.value
    def sleep(self, seconds): self.sleeps.append(seconds); self.value += seconds


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
    session = OutcomeSession([
        FakeResponse({}, 429, {"Retry-After": "45"}), FakeResponse(raw_location()),
    ])
    client = OpenMeteoHourlyClient(
        session=session, minimum_interval_seconds=15, sleep=clock.sleep,
        monotonic=clock.monotonic, max_attempts=3,
    )
    assert len(client.fetch_range([(31.8, 35.1)], NOW - timedelta(hours=1), NOW)) == 1
    assert clock.sleeps == [45] and len(session.calls) == 2


def test_repeated_429_opens_cooldown_and_prevents_more_http_calls():
    clock = FakeClock()
    session = OutcomeSession([
        FakeResponse({}, 429), FakeResponse({}, 429), FakeResponse(raw_location()),
    ])
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
