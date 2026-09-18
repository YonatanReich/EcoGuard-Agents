from __future__ import annotations

import gzip
import json

from ecoguard.shared.air_pollution_history import read_history_month


def _write_cache(tmp_path, points):
    path = tmp_path / "station_1" / "channel_4_no2" / "2021-01.json.gz"
    path.parent.mkdir(parents=True)
    payload = {
        "schema_version": "ecoguard-air-pollution-five-minute-cache-v1",
        "complete": True,
        "source": "Israel Ministry of Environmental Protection / Envista",
        "station_id": "1", "station_name": "Station", "channel_id": "4",
        "pollutant": "NO2", "year": 2021, "month": 1,
        "request_semantics": {
            "resolution": "provider five-minute averages", "timeBeginning": False,
            "quality_filter_applied": False, "unit_filter_applied": False,
            "off_grid_filter_applied": False,
        },
        "point_count": len(points), "points": points,
    }
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
    return path


def _point(timestamp, value, *, valid=True, unit="µg/m³"):
    return {"datetime": timestamp, "channels": [{
        "id": 4, "name": "NO2", "value": value, "valid": valid,
        "status": 1, "units": unit,
    }]}


def test_reader_preserves_signed_valid_values_and_last_revision(tmp_path):
    stamp = "2021-01-01T00:00:00+02:00"
    month = read_history_month(_write_cache(tmp_path, [
        _point(stamp, -2.0), _point(stamp, -1.5),
        _point("2021-01-01T00:05:00+02:00", -9999),
        _point("2021-01-01T00:10:00+02:00", 4.0, valid=False),
        _point("2021-01-01T00:15:00+02:00", float("inf")),
    ]))
    assert [(item.value, item.unit, item.provider_unit) for item in month.observations] == [
        (-1.5, "µg/m³", "µg/m³")
    ]
    assert month.quality_summary == {
        "accepted_unique_observations": 1,
        "duplicate_timestamp_revisions": 1,
        "missing_malformed_or_nonfinite": 1,
        "provider_invalid": 1,
        "raw_points": 5,
        "sentinel": 1,
    }


def test_reader_rejects_off_grid_timestamp_without_snapping(tmp_path):
    month = read_history_month(_write_cache(tmp_path, [
        _point("2021-01-01T00:03:00+02:00", 1.0),
        _point("2021-01-01T00:05:00+02:00", 2.0),
    ]))
    assert [item.observed_at.minute for item in month.observations] == [5]
    assert month.quality_summary["off_grid_timestamps"] == 1
