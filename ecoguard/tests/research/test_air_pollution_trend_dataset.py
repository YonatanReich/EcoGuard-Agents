from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta

from ecoguard.research.datasets.build_air_pollution_trend_dataset import build_dataset
from ecoguard.shared.air_pollution_trend_features import PROVIDER_TIMEZONE


def _point(moment, value):
    return {"datetime": moment.isoformat(), "channels": [{
        "id": 4, "name": "NO2", "value": value, "valid": True,
        "status": 1, "units": "µg/m³",
    }]}


def _month(cache, year, month, points):
    path = cache / "station_1" / "channel_4_no2" / f"{year:04d}-{month:02d}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "ecoguard-air-pollution-five-minute-cache-v1",
        "complete": True,
        "source": "Israel Ministry of Environmental Protection / Envista",
        "station_id": "1", "station_name": "Station", "channel_id": "4",
        "pollutant": "NO2", "year": year, "month": month,
        "request_semantics": {
            "resolution": "provider five-minute averages", "timeBeginning": False,
            "quality_filter_applied": False, "unit_filter_applied": False,
            "off_grid_filter_applied": False,
        },
        "point_count": len(points), "points": points,
    }
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)


def test_builder_uses_month_halo_and_is_byte_deterministic(tmp_path):
    cache = tmp_path / "cache"
    start = datetime(2021, 1, 31, 21, 30, tzinfo=PROVIDER_TIMEZONE)
    moments = [start + timedelta(minutes=5 * index) for index in range(34)]
    january = [
        _point(moment, index - 3)
        for index, moment in enumerate(moments) if moment.month == 1
    ]
    february = [
        _point(moment, index - 3)
        for index, moment in enumerate(moments) if moment.month == 2
    ]
    _month(cache, 2021, 1, january)
    _month(cache, 2021, 2, february)

    manifests = []
    for name in ("one", "two"):
        manifests.append(build_dataset(
            cache_dir=cache,
            output_dir=tmp_path / name,
            pollutant="NO2",
            years={2021},
            month_filter=1,
            max_series=1,
            epsilons={"NO2": 1.0},
            epsilon_version="test-only-v1",
        ))
    assert manifests[0] == manifests[1]
    first_files = sorted(
        path.relative_to(tmp_path / "one")
        for path in (tmp_path / "one").rglob("*") if path.is_file()
    )
    second_files = sorted(
        path.relative_to(tmp_path / "two")
        for path in (tmp_path / "two").rglob("*") if path.is_file()
    )
    assert first_files == second_files
    assert all(
        (tmp_path / "one" / path).read_bytes() == (tmp_path / "two" / path).read_bytes()
        for path in first_files
    )

    manifest = manifests[0]
    assert manifest["development_limit"]["active"] is True
    assert manifest["sampling_or_downsampling"] is False
    assert sum(manifest["class_counts"].values()) == manifest["counts"]["included_examples"]
    assert manifest["negative_value_report"]["accepted_negative_values_in_candidate_periods"] == 3
    part = next((tmp_path / "one").rglob("*.csv.gz"))
    with gzip.open(part, "rt", encoding="utf-8") as stream:
        text = stream.read()
    assert "2021-01-31T23:30:00+02:00" in text
    assert "2021-02-01T00:00:00+02:00" in text
