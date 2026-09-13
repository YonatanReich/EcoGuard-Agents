from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ecoguard.research.datasets.build_historical_environmental_features import PriorFirmsIndex
from ecoguard.research.training.train_fire_prediction_landcover_terrain_models import FULL_FEATURES
from ecoguard.analyzers.emergency.fire.feature_builder import CurrentRiskFeatureBuilder
from ecoguard.analyzers.emergency.fire.static_feature_store import STATIC_MODEL_FEATURES
from ecoguard.shared.weather_features import FEATURE_FIELDS


NOW = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)


class FakeWeatherSource:
    def __init__(self, response):
        self.response, self.calls = response, []
    def features_for_cell(self, cell_id, evaluation_time):
        self.calls.append((cell_id, evaluation_time))
        return self.response


def make_grid(path):
    columns = ",".join(f"{name} REAL" for name in STATIC_MODEL_FEATURES)
    connection = sqlite3.connect(path)
    connection.execute(
        f"CREATE TABLE risk_grid_cells(cell_id TEXT PRIMARY KEY,latitude REAL,longitude REAL,active INTEGER,feature_status TEXT,{columns})"
    )
    values = {name: 1.0 for name in STATIC_MODEL_FEATURES}
    connection.execute(
        f"INSERT INTO risk_grid_cells VALUES(?,?,?,?,?,{','.join('?' for _ in STATIC_MODEL_FEATURES)})",
        ("cell-a", 31.8, 35.2, 1, "complete", *(values[name] for name in STATIC_MODEL_FEATURES)),
    )
    connection.commit(); connection.close()


def test_assembles_exact_44_features_from_stored_observations_and_static_store(tmp_path):
    grid = tmp_path / "grid.sqlite"
    make_grid(grid)
    weather = FakeWeatherSource({
        "status": "success", "reason": None,
        "features": {name: 1.0 for name in FEATURE_FIELDS},
    })
    builder = CurrentRiskFeatureBuilder(grid_path=grid, weather_source=weather, firms_index=PriorFirmsIndex([]))
    result = builder.build(31.8, 35.2, NOW)
    assert result["status"] == "success"
    assert set(result["features"]) == set(FULL_FEATURES)
    assert len(result["features"]) == 44
    assert weather.calls == [("cell-a", NOW)]
    assert result["features"]["fires_within_5km_previous_30d"] == 0
    assert result["features"]["days_since_previous_firms_candidate_within_10km"] != result["features"]["days_since_previous_firms_candidate_within_10km"]


def test_unmapped_or_stale_weather_fails_without_fabrication(tmp_path):
    grid = tmp_path / "grid.sqlite"
    make_grid(grid)
    for response, reason in (
        ({"status": "unavailable", "reason": "weather_history_unavailable", "features": {}}, "weather_history_unavailable"),
        ({"status": "stale", "reason": "weather_history_incomplete", "features": {}}, "weather_history_incomplete"),
    ):
        builder = CurrentRiskFeatureBuilder(
            grid_path=grid, weather_source=FakeWeatherSource(response), firms_index=PriorFirmsIndex([])
        )
        result = builder.build(31.8, 35.2, NOW)
        assert result["status"] == "unavailable"
        assert result["reason"] == reason
        assert result["features"] is None
