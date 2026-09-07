"""Assemble the existing 44 Current Risk predictors from local persisted data."""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.datasets.build_historical_environmental_features import PriorFirmsIndex, historical_fire_features
from research.datasets.build_historical_fire_negative_samples import FIRMS_INPUT, NegativeSampleError, load_firms_incidents
from services.rolling_weather_cache import DEFAULT_CACHE_PATH, RollingWeatherCache, WeatherCacheError
from services.static_feature_store import DEFAULT_DATABASE_PATH, STATIC_MODEL_FEATURES


SEASON_FEATURES = ("sin_day_of_year", "cos_day_of_year", "sin_hour", "cos_hour")
FIRMS_FEATURES = (
    "fires_within_5km_previous_30d",
    "fires_within_10km_previous_90d",
    "fires_within_25km_previous_365d",
    "days_since_previous_firms_candidate_within_10km",
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    first, second = math.radians(lat1), math.radians(lat2)
    delta_lat = second - first
    delta_lon = math.radians(lon2 - lon1)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(first) * math.cos(second) * math.sin(delta_lon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(value)))


class CurrentRiskFeatureBuilder:
    """Build model input without provider calls or static-feature recomputation."""

    def __init__(
        self,
        *,
        grid_path: Path | str = DEFAULT_DATABASE_PATH,
        weather_cache: RollingWeatherCache | None = None,
        firms_path: Path | str = FIRMS_INPUT,
        firms_index: PriorFirmsIndex | None = None,
        maximum_cell_distance_km: float = 5.0,
    ):
        self.grid_path = Path(grid_path)
        self.weather_cache = weather_cache or RollingWeatherCache(DEFAULT_CACHE_PATH)
        self.firms_path = Path(firms_path)
        self._firms_index = firms_index
        self.maximum_cell_distance_km = maximum_cell_distance_km

    def _cell(self, latitude: float, longitude: float) -> dict[str, Any] | None:
        if not self.grid_path.exists():
            return None
        connection = sqlite3.connect(self.grid_path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT * FROM risk_grid_cells WHERE active=1").fetchall()
        except sqlite3.Error:
            return None
        finally:
            connection.close()
        if not rows:
            return None
        row = min(rows, key=lambda item: _haversine_km(latitude, longitude, item["latitude"], item["longitude"]))
        distance = _haversine_km(latitude, longitude, row["latitude"], row["longitude"])
        return dict(row) if distance <= self.maximum_cell_distance_km else None

    def _cell_by_id(self, cell_id: str) -> dict[str, Any] | None:
        if not self.grid_path.exists():
            return None
        connection = sqlite3.connect(self.grid_path)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT * FROM risk_grid_cells WHERE active=1 AND cell_id=?", (cell_id,)
            ).fetchone()
            return dict(row) if row else None
        except sqlite3.Error:
            return None
        finally:
            connection.close()

    def _index(self) -> PriorFirmsIndex:
        if self._firms_index is None:
            self._firms_index = PriorFirmsIndex(load_firms_incidents(self.firms_path))
        return self._firms_index

    def build(self, latitude: float, longitude: float, evaluation_time: datetime | None = None) -> dict[str, Any]:
        evaluation = (evaluation_time or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        cell = self._cell(latitude, longitude)
        return self._build_cell(cell, evaluation)

    def build_for_cell(self, cell_id: str, evaluation_time: datetime | None = None) -> dict[str, Any]:
        """Build the same 44 features for an exact active grid cell."""
        evaluation = (evaluation_time or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        return self._build_cell(self._cell_by_id(cell_id), evaluation, requested_cell_id=cell_id)

    def build_for_cell_record(self, cell: dict[str, Any], evaluation_time: datetime) -> dict[str, Any]:
        """Build from a grid row already loaded by a bulk scanner."""
        evaluation = evaluation_time.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        return self._build_cell(cell, evaluation, requested_cell_id=str(cell.get("cell_id", "")))

    def _build_cell(
        self, cell: dict[str, Any] | None, evaluation: datetime, requested_cell_id: str | None = None,
    ) -> dict[str, Any]:
        if cell is None:
            return {"status": "unavailable", "reason": "active_grid_cell_not_found", "features": None, "cell_id": requested_cell_id}
        if cell.get("feature_status") != "complete" or any(cell.get(name) is None for name in STATIC_MODEL_FEATURES):
            return {"status": "unavailable", "reason": "static_features_incomplete", "features": None, "cell_id": cell["cell_id"]}
        if not self.weather_cache.path.exists():
            return {"status": "unavailable", "reason": "weather_cache_missing", "features": None, "cell_id": cell["cell_id"]}
        try:
            weather = self.weather_cache.features_for_cell(cell["cell_id"], evaluation)
        except (OSError, sqlite3.Error, WeatherCacheError):
            return {"status": "unavailable", "reason": "weather_cache_unavailable", "features": None, "cell_id": cell["cell_id"]}
        if weather["status"] != "success":
            return {
                "status": "unavailable", "reason": weather.get("reason", "weather_cache_stale"),
                "features": None, "cell_id": cell["cell_id"], "weather_node_id": weather.get("weather_node_id"),
            }
        try:
            firms = historical_fire_features(
                self._index(), float(cell["latitude"]), float(cell["longitude"]), evaluation
            )
        except (OSError, ValueError, KeyError, NegativeSampleError):
            return {"status": "unavailable", "reason": "firms_history_unavailable", "features": None, "cell_id": cell["cell_id"]}
        day = evaluation.timetuple().tm_yday
        features = dict(weather["features"])
        features.update({
            "sin_day_of_year": math.sin(2 * math.pi * day / 365.25),
            "cos_day_of_year": math.cos(2 * math.pi * day / 365.25),
            "sin_hour": math.sin(2 * math.pi * evaluation.hour / 24),
            "cos_hour": math.cos(2 * math.pi * evaluation.hour / 24),
        })
        features.update(firms)
        features.update({name: cell[name] for name in STATIC_MODEL_FEATURES})
        if features["days_since_previous_firms_candidate_within_10km"] is None:
            features["days_since_previous_firms_candidate_within_10km"] = float("nan")
        return {
            "status": "success", "reason": None, "features": features,
            "cell_id": cell["cell_id"], "weather_node_id": weather["weather_node_id"],
            "evaluation_time": evaluation.isoformat().replace("+00:00", "Z"),
        }
