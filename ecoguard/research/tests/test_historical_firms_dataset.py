from datetime import date
import time
from unittest.mock import MagicMock

import pytest
import requests
import ecoguard.research.datasets.build_historical_firms_dataset as historical_firms

from ecoguard.research.datasets.build_historical_firms_dataset import (
    CheckpointError,
    CheckpointStore,
    FirmsProviderError,
    ProductAvailability,
    HistoricalFirmsClient,
    RequestWindow,
    checkpoint_configuration,
    cluster_hotspots,
    deduplicate_hotspots,
    download_hotspots,
    format_progress,
    normalize_firms_row,
    parse_acquisition_timestamp,
    parse_firms_csv,
    plan_product_windows,
    validate_product_plan,
)


def raw_row(**overrides):
    row = {
        "latitude": "31.9000",
        "longitude": "34.9000",
        "bright_ti4": "340.1",
        "scan": "0.4",
        "track": "0.5",
        "acq_date": "2024-06-01",
        "acq_time": "35",
        "satellite": "N20",
        "instrument": "VIIRS",
        "confidence": "n",
        "version": "2.0",
        "bright_ti5": "300.2",
        "frp": "8.5",
        "daynight": "N",
    }
    row.update(overrides)
    return row


def observation(latitude=31.9, longitude=34.9, timestamp="2024-06-01T00:35:00Z", suffix="a"):
    return {
        "hotspot_id": f"hotspot-{suffix}",
        "latitude": latitude,
        "longitude": longitude,
        "acquisition_timestamp": timestamp,
        "satellite": "N20",
        "source_product": "VIIRS_NOAA20_SP",
        "frp": 8.5,
    }


def test_firms_row_parsing_and_timestamp_construction():
    record = normalize_firms_row(raw_row(), "VIIRS_NOAA20_SP")
    assert record["acquisition_time"] == "0035"
    assert record["acquisition_timestamp"] == "2024-06-01T00:35:00Z"
    assert record["frp"] == 8.5
    assert record["source"] == "NASA FIRMS"
    assert record["source_product"] == "VIIRS_NOAA20_SP"
    assert record["hotspot_id"].startswith("firms_")


def test_timestamp_rejects_invalid_time():
    with pytest.raises(ValueError):
        parse_acquisition_timestamp("2024-06-01", "2561")


def test_csv_parser_skips_malformed_rows():
    header = ",".join(raw_row().keys())
    valid = ",".join(raw_row().values())
    invalid = ",".join(raw_row(latitude="bad").values())
    records, malformed = parse_firms_csv(f"{header}\n{valid}\n{invalid}\n", "VIIRS_NOAA20_SP")
    assert len(records) == 1
    assert malformed == 1


def test_nearby_observations_form_one_candidate():
    records = [
        observation(suffix="a"),
        observation(31.904, 34.904, "2024-06-01T12:00:00Z", "b"),
    ]
    candidates = cluster_hotspots(records)
    assert len(candidates) == 1
    assert candidates[0]["hotspot_count"] == 2
    assert candidates[0]["duration_hours"] == pytest.approx(11.416667)


def test_distant_observations_are_separate():
    records = [observation(suffix="a"), observation(32.0, 35.0, suffix="b")]
    assert len(cluster_hotspots(records)) == 2


def test_large_temporal_gap_creates_separate_candidate():
    records = [
        observation(suffix="a"),
        observation(timestamp="2024-06-03T00:35:00Z", suffix="b"),
    ]
    assert len(cluster_hotspots(records)) == 2


def test_multi_day_cluster_is_bounded_by_maximum_duration():
    records = [
        observation(timestamp="2024-06-01T00:00:00Z", suffix="a"),
        observation(timestamp="2024-06-02T00:00:00Z", suffix="b"),
        observation(timestamp="2024-06-03T00:00:00Z", suffix="c"),
        observation(timestamp="2024-06-04T00:00:00Z", suffix="d"),
        observation(timestamp="2024-06-05T00:00:00Z", suffix="e"),
    ]
    candidates = cluster_hotspots(records)
    assert [item["hotspot_count"] for item in candidates] == [4, 1]
    assert candidates[0]["duration_hours"] == 72.0


def reference_cluster_hotspots(records, spatial=1.5, temporal=24.0, duration=72.0):
    """Previous greedy implementation retained as a small semantic oracle."""
    ordered = historical_firms.deduplicate_hotspots(records)
    clusters = []
    for record in ordered:
        current_time = historical_firms._timestamp(record)
        choices = []
        for index, cluster in enumerate(clusters):
            start = historical_firms._timestamp(cluster[0])
            latest = historical_firms._timestamp(cluster[-1])
            gap = (current_time - latest).total_seconds() / 3600
            span = (current_time - start).total_seconds() / 3600
            if gap < 0 or gap > temporal or span > duration:
                continue
            distance = historical_firms.haversine_km(
                record, historical_firms._cluster_centroid(cluster)
            )
            if distance <= spatial:
                choices.append((distance, index))
        if choices:
            clusters[min(choices)[1]].append(record)
        else:
            clusters.append([record])
    return [historical_firms._build_candidate(cluster) for cluster in clusters]


def test_indexed_clustering_matches_previous_greedy_semantics():
    records = [
        observation(31.900, 34.900, "2024-06-01T00:00:00Z", "a"),
        observation(31.905, 34.905, "2024-06-01T06:00:00Z", "b"),
        observation(32.100, 35.100, "2024-06-01T07:00:00Z", "c"),
        observation(31.907, 34.907, "2024-06-02T05:00:00Z", "d"),
        observation(31.908, 34.908, "2024-06-04T00:00:00Z", "e"),
        observation(32.101, 35.101, "2024-06-04T01:00:00Z", "f"),
    ]

    assert cluster_hotspots(records) == reference_cluster_hotspots(records)


def test_duplicate_observation_is_removed():
    record = observation()
    assert len(deduplicate_hotspots([record, dict(record)])) == 1
    assert cluster_hotspots([record, dict(record)])[0]["hotspot_count"] == 1


def test_out_of_bounds_or_malformed_input_is_not_invented():
    assert normalize_firms_row(raw_row(latitude="bad"), "VIIRS_NOAA20_SP") is None
    assert normalize_firms_row(raw_row(longitude="40"), "VIIRS_NOAA20_SP") is None


def test_sp_products_are_preferred_and_nrt_only_fills_later_dates():
    availability = {
        "VIIRS_NOAA20_SP": ProductAvailability(
            "VIIRS_NOAA20_SP", date(2023, 1, 1), date(2025, 12, 31)
        ),
        "VIIRS_NOAA20_NRT": ProductAvailability(
            "VIIRS_NOAA20_NRT", date(2025, 10, 1), date(2026, 8, 27)
        ),
    }
    plans = plan_product_windows(availability, date(2023, 1, 1), date(2026, 8, 27))
    assert plans == [
        ("VIIRS_NOAA20_SP", date(2023, 1, 1), date(2025, 12, 31)),
        ("VIIRS_NOAA20_NRT", date(2026, 1, 1), date(2026, 8, 27)),
    ]
    validate_product_plan(
        availability, date(2023, 1, 1), date(2026, 8, 27), plans
    )


def test_realistic_noaa20_boundary_has_no_overlap_or_gap():
    availability = {
        "VIIRS_NOAA20_SP": ProductAvailability(
            "VIIRS_NOAA20_SP", date(2018, 4, 1), date(2026, 5, 31)
        ),
        "VIIRS_NOAA20_NRT": ProductAvailability(
            "VIIRS_NOAA20_NRT", date(2026, 6, 1), date(2026, 8, 27)
        ),
    }
    plans = plan_product_windows(
        availability, date(2023, 1, 1), date(2026, 8, 27)
    )

    assert plans[-2:] == [
        ("VIIRS_NOAA20_SP", date(2023, 1, 1), date(2026, 5, 31)),
        ("VIIRS_NOAA20_NRT", date(2026, 6, 1), date(2026, 8, 27)),
    ]
    validate_product_plan(
        availability, date(2023, 1, 1), date(2026, 8, 27), plans
    )


def test_product_plan_rejects_official_availability_gap():
    availability = {
        "VIIRS_NOAA20_SP": ProductAvailability(
            "VIIRS_NOAA20_SP", date(2024, 1, 1), date(2024, 3, 5)
        ),
        "VIIRS_NOAA20_NRT": ProductAvailability(
            "VIIRS_NOAA20_NRT", date(2024, 3, 11), date(2024, 4, 1)
        ),
    }
    plans = plan_product_windows(
        availability, date(2024, 1, 1), date(2024, 4, 1)
    )

    with pytest.raises(FirmsProviderError, match="availability gap"):
        validate_product_plan(
            availability, date(2024, 1, 1), date(2024, 4, 1), plans
        )


def test_provider_http_error_is_safe_and_does_not_expose_api_key():
    key = "secret-map-key"
    response = MagicMock(status_code=403)
    session = MagicMock()
    session.headers = {}
    session.get.side_effect = requests.exceptions.HTTPError(response=response)
    client = HistoricalFirmsClient(api_key=key, session=session)

    with pytest.raises(FirmsProviderError) as caught:
        client.fetch_window("VIIRS_NOAA20_SP", (34.2, 29.4, 35.9, 33.4), date(2024, 1, 1), 5)

    assert str(caught.value) == "authentication error"
    assert key not in str(caught.value)


def test_http_400_invalid_map_key_is_classified_as_authentication_without_retry():
    response = MagicMock(status_code=400, text="Invalid MAP_KEY.")
    session = MagicMock()
    session.headers = {}
    session.get.side_effect = requests.exceptions.HTTPError(response=response)
    sleep = MagicMock()
    client = HistoricalFirmsClient(
        api_key="secret", session=session, sleep_function=sleep
    )

    with pytest.raises(FirmsProviderError, match="^authentication error$"):
        client.fetch_window(
            "VIIRS_NOAA20_SP", (34.2, 29.4, 35.9, 33.4), date(2026, 3, 6), 5
        )

    assert session.get.call_count == 1
    sleep.assert_not_called()


def test_provider_timeout_has_one_bounded_retry(monkeypatch):
    session = MagicMock()
    session.headers = {}
    session.get.side_effect = requests.exceptions.Timeout()
    sleep = MagicMock()
    client = HistoricalFirmsClient(
        api_key="secret", session=session, max_retry_attempts=2, sleep_function=sleep
    )

    with pytest.raises(FirmsProviderError) as caught:
        client.fetch_window("VIIRS_NOAA20_SP", (34.2, 29.4, 35.9, 33.4), date(2024, 1, 1), 5)

    assert str(caught.value) == "timeout"
    assert session.get.call_count == 2
    sleep.assert_called_once_with(2.0)


def successful_response(text="ok"):
    response = MagicMock(status_code=200, text=text)
    response.raise_for_status.return_value = None
    return response


def test_transient_failure_retries_then_succeeds_with_safe_log():
    session = MagicMock()
    session.headers = {}
    session.get.side_effect = [
        requests.exceptions.Timeout(),
        successful_response("csv result"),
    ]
    logs = []
    sleep = MagicMock()
    client = HistoricalFirmsClient(
        api_key="secret-key",
        session=session,
        sleep_function=sleep,
        retry_logger=logs.append,
    )

    result = client.fetch_window(
        "VIIRS_NOAA20_SP", (34.2, 29.4, 35.9, 33.4), date(2024, 1, 1), 5
    )

    assert result == "csv result"
    assert session.get.call_count == 2
    sleep.assert_called_once_with(2.0)
    assert "attempt 2/4" in logs[0]
    assert "secret-key" not in logs[0]
    assert "http" not in logs[0].casefold()


def test_transient_retry_limit_uses_bounded_exponential_backoff():
    session = MagicMock()
    session.headers = {}
    session.get.side_effect = requests.exceptions.Timeout()
    sleep = MagicMock()
    client = HistoricalFirmsClient(
        api_key="secret",
        session=session,
        max_retry_attempts=4,
        sleep_function=sleep,
        retry_logger=MagicMock(),
    )

    with pytest.raises(FirmsProviderError, match="^timeout$"):
        client.fetch_window(
            "VIIRS_NOAA20_SP", (34.2, 29.4, 35.9, 33.4), date(2024, 1, 1), 5
        )

    assert session.get.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [2.0, 4.0, 8.0]


def test_permanent_http_failure_is_not_retried():
    session = MagicMock()
    session.headers = {}
    response = MagicMock(status_code=400)
    session.get.side_effect = requests.exceptions.HTTPError(response=response)
    sleep = MagicMock()
    client = HistoricalFirmsClient(
        api_key="secret", session=session, sleep_function=sleep
    )

    with pytest.raises(FirmsProviderError, match=r"HTTP error \(status 400\)"):
        client.fetch_window(
            "VIIRS_NOAA20_SP", (34.2, 29.4, 35.9, 33.4), date(2024, 1, 1), 5
        )

    assert session.get.call_count == 1
    sleep.assert_not_called()


def checkpoint_config(window):
    return checkpoint_configuration(
        start=date(2024, 1, 1),
        end=date(2024, 1, 5),
        windows=[window],
        max_spatial_distance_km=1.5,
        max_temporal_gap_hours=24.0,
        max_incident_duration_hours=72.0,
    )


def test_checkpoint_is_created_and_round_trips(tmp_path):
    window = RequestWindow("VIIRS_NOAA20_SP", date(2024, 1, 1), 5)
    store = CheckpointStore(tmp_path / "checkpoint", checkpoint_config(window))
    store.initialize()
    record = normalize_firms_row(raw_row(), "VIIRS_NOAA20_SP")
    store.save_window(window, [record], 2)

    assert (tmp_path / "checkpoint" / "manifest.json").exists()
    assert store.load_window(window) == ([record], 2)


def test_corrupted_checkpoint_window_fails_clearly(tmp_path):
    window = RequestWindow("VIIRS_NOAA20_SP", date(2024, 1, 1), 5)
    store = CheckpointStore(tmp_path / "checkpoint", checkpoint_config(window))
    store.initialize()
    store.save_window(window, [normalize_firms_row(raw_row(), window.product)], 0)
    store._window_path(window).write_text("{corrupt", encoding="utf-8")

    with pytest.raises(CheckpointError, match="checkpoint window is corrupted"):
        store.load_window(window)


def test_incompatible_checkpoint_fails_clearly(tmp_path):
    window = RequestWindow("VIIRS_NOAA20_SP", date(2024, 1, 1), 5)
    directory = tmp_path / "checkpoint"
    CheckpointStore(directory, checkpoint_config(window)).initialize()
    changed = {**checkpoint_config(window), "max_spatial_distance_km": 2.0}

    with pytest.raises(CheckpointError, match="checkpoint is incompatible"):
        CheckpointStore(directory, changed).initialize()


class FakeHistoricalClient:
    def __init__(self, csv_text):
        self.csv_text = csv_text
        self.fetch_calls = []
        self.availability_calls = 0

    def discover_availability(self):
        self.availability_calls += 1
        return {
            "VIIRS_NOAA20_SP": ProductAvailability(
                "VIIRS_NOAA20_SP", date(2024, 1, 1), date(2024, 1, 6)
            )
        }

    def fetch_window(self, product, bounds, start, days):
        self.fetch_calls.append((product, bounds, start, days))
        return self.csv_text


def valid_csv():
    row = raw_row()
    return ",".join(row) + "\n" + ",".join(row.values()) + "\n"


def test_progress_accounting_and_checkpoint_resume(tmp_path, monkeypatch):
    monkeypatch.setattr("research.datasets.build_historical_firms_dataset.time.sleep", MagicMock())
    logs = []
    clock = iter([100.0, 101.0, 102.0])
    first_client = FakeHistoricalClient(valid_csv())
    records, _, _ = download_hotspots(
        first_client,
        date(2024, 1, 1),
        date(2024, 1, 6),
        checkpoint_directory=tmp_path / "checkpoint",
        progress_logger=logs.append,
        monotonic_function=lambda: next(clock),
    )

    assert len(first_client.fetch_calls) == 2
    assert len(records) == 1
    assert "Progress: 1 / 2 requests (50.0%)" in logs[0]
    assert "Window: 2024-01-01 -> 2024-01-05" in logs[0]
    assert "Elapsed: 00:00:01" in logs[0]
    assert "Progress: 2 / 2 requests (100.0%)" in logs[1]

    offline_logs = []
    offline_clock = iter([150.0, 151.0, 152.0])
    offline_client = FakeHistoricalClient(valid_csv())
    offline_records, offline_availability, _ = download_hotspots(
        offline_client,
        date(2024, 1, 1),
        date(2024, 1, 6),
        checkpoint_directory=tmp_path / "checkpoint",
        progress_logger=offline_logs.append,
        monotonic_function=lambda: next(offline_clock),
    )

    assert offline_client.availability_calls == 0
    assert offline_client.fetch_calls == []
    assert offline_availability == {}
    assert offline_records == records
    assert offline_logs[-1] == "Loaded 1 unique hotspots from checkpoint."

    missing_window = RequestWindow("VIIRS_NOAA20_SP", date(2024, 1, 6), 1)
    (tmp_path / "checkpoint" / "windows" / f"{missing_window.key}.json").unlink()
    resumed_logs = []
    resumed_clock = iter([200.0, 201.0, 202.0, 203.0, 204.0])
    resumed_client = FakeHistoricalClient(valid_csv())
    resumed_records, _, _ = download_hotspots(
        resumed_client,
        date(2024, 1, 1),
        date(2024, 1, 6),
        checkpoint_directory=tmp_path / "checkpoint",
        progress_logger=resumed_logs.append,
        monotonic_function=lambda: next(resumed_clock),
    )

    assert len(resumed_client.fetch_calls) == 1
    assert resumed_client.fetch_calls[0][2:] == (date(2024, 1, 6), 1)
    assert resumed_records == records
    assert "Source: checkpoint" in resumed_logs[0]
    assert "Source: download" in resumed_logs[1]


def test_clustering_large_spatially_separated_input_is_not_quadratic(monkeypatch):
    records = []
    for row in range(100):
        for column in range(60):
            suffix = f"{row}-{column}"
            records.append(
                observation(
                    latitude=29.5 + row * 0.02,
                    longitude=34.3 + column * 0.02,
                    timestamp="2024-06-01T00:00:00Z",
                    suffix=suffix,
                )
            )

    distance_calls = 0
    original_haversine = historical_firms.haversine_km

    def counted_haversine(first, second):
        nonlocal distance_calls
        distance_calls += 1
        return original_haversine(first, second)

    monkeypatch.setattr(historical_firms, "haversine_km", counted_haversine)
    started_at = time.perf_counter()
    candidates = cluster_hotspots(records)
    elapsed = time.perf_counter() - started_at

    assert len(candidates) == 6000
    assert distance_calls < len(records) * 12
    assert elapsed < 5.0
