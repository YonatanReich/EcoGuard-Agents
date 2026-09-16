"""Normalization of multiple stations into one cell observation."""

from datetime import datetime, timezone

from ecoguard.collection.flood.signal_rows import rainfall_signal_records


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
