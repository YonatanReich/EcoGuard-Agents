"""Normalization of multiple stations into one cell observation."""

from datetime import datetime, timezone

from ecoguard.collectors.flood.signal_rows import (
    hydrometric_signal_records,
    rainfall_signal_records,
)


def test_stations_in_one_cell_and_time_share_one_sorted_payload():
    at = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)
    rows = [
        {"source_station_id": 2, "observed_at": at, "rainfall_mm": 0.7},
        {"source_station_id": 1, "observed_at": at, "rainfall_mm": 0.5},
        {"source_station_id": 999, "observed_at": at, "rainfall_mm": 1.0},
    ]
    stations = {
        1: {
            "cell_id": "cell-a",
            "latitude": 32.0,
            "longitude": 34.8,
            "name_he": "א",
            "name_en": "A",
            "drainage_basin_id": 11,
        },
        2: {
            "cell_id": "cell-a",
            "latitude": 32.01,
            "longitude": 34.81,
            "name_he": "ב",
            "name_en": "B",
        },
    }

    records = rainfall_signal_records(rows, stations)

    assert len(records) == 1
    assert records[0]["cell_id"] == "cell-a"
    assert [
        item["source_station_id"] for item in records[0]["payload"]["stations"]
    ] == [1, 2]
    assert records[0]["payload"]["stations"][0]["drainage_basin_id"] == 11


def test_hydrometric_signals_exclude_stations_without_thresholds():
    at = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)
    rows = [
        {"source_station_id": 1, "observed_at": at, "discharge_m3s": 12.0,
         "water_height_m": 1.2},
        {"source_station_id": 2, "observed_at": at, "discharge_m3s": 7.0,
         "water_height_m": 0.8},
    ]
    stations = {
        1: {
            "cell_id": "cell-a",
            "latitude": 32.0,
            "longitude": 34.8,
            "flow_threshold_status": "complete_thresholds",
        },
        2: {
            "cell_id": "cell-a",
            "latitude": 32.01,
            "longitude": 34.81,
            "flow_threshold_status": "missing_thresholds",
        },
    }

    records = hydrometric_signal_records(rows, stations)

    assert len(records) == 1
    assert [
        station["source_station_id"]
        for station in records[0]["payload"]["stations"]
    ] == [1]


def test_hydrometric_signals_are_empty_when_only_station_has_no_thresholds():
    at = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)
    rows = [
        {"source_station_id": 2, "observed_at": at, "discharge_m3s": 7.0,
         "water_height_m": 0.8},
    ]
    stations = {
        2: {
            "cell_id": "cell-a",
            "latitude": 32.01,
            "longitude": 34.81,
            "flow_threshold_status": "missing_thresholds",
        },
    }

    assert hydrometric_signal_records(rows, stations) == []
