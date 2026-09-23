"""Assemble the existing 44 Current Risk predictors from local persisted data."""

from __future__ import annotations

import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from ecoguard.database.repositories.weather_history import (
    HISTORY_HOURS, hourly_for_cell, hourly_for_cells,
)
from ecoguard.analyzers.fire.ml.build_historical_environmental_features import PriorFirmsIndex, historical_fire_features
from ecoguard.analyzers.fire.ml.build_historical_fire_negative_samples import FIRMS_INPUT, NegativeSampleError, load_firms_incidents
from ecoguard.analyzers.fire.static_feature_store import DEFAULT_DATABASE_PATH, STATIC_MODEL_FEATURES
from ecoguard.shared.weather_features import compute_features


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


def feature_window(evaluation: datetime) -> tuple[datetime, datetime]:
    """The hours compute_features reads behind an evaluation time.

    Its widest window is precipitation_sum_7d, which sums [evaluation - 168h,
    evaluation). The newest hour that can contribute is therefore evaluation-1h
    and the oldest is evaluation-168h — 168 hours inclusive, which is what
    HISTORY_HOURS names and what the collector backfills to.
    """
    end = evaluation - timedelta(hours=1)
    return end - timedelta(hours=HISTORY_HOURS - 1), end


class StoredWeatherFeatures:
    """Model weather features read from the observations table.

    Replaced a private SQLite cache that fetched its own copy of the same seven
    variables from Open-Meteo. The model and its feature definitions did not
    change: compute_features is pure, so swapping where the hourly series comes
    from is invisible to it.

    `window` preloads many cells for one evaluation time. A national scan asks
    for all 1,174, and against a hosted database the per-cell round trip is the
    whole cost.
    """

    def __init__(self) -> None:
        self._preloaded: dict[str, dict[str, Any]] | None = None

    @contextmanager
    def window(self, cell_ids, evaluation: datetime):
        start, end = feature_window(evaluation)
        self._preloaded = hourly_for_cells(list(cell_ids), start, end)
        try:
            yield self
        finally:
            self._preloaded = None

    def features_for_cell(self, cell_id: str, evaluation_time: datetime) -> dict[str, Any]:
        stored = (self._preloaded or {}).get(cell_id)
        if stored is None:
            start, end = feature_window(evaluation_time)
            stored = hourly_for_cell(cell_id, start, end)
        features, status = compute_features(stored, evaluation_time)
        if stored["status"] != "success" or status != "success":
            # An incomplete history is reported, never smoothed over. A model
            # scored on a series with holes in it produces a number that looks
            # exactly like a real one.
            return {
                "status": "stale", "reason": "weather_history_incomplete",
                "missing_hours": stored["missing_hours"], "features": features,
            }
        return {"status": "success", "reason": None, "missing_hours": 0, "features": features}


class CurrentRiskFeatureBuilder:
    """Build model input without provider calls or static-feature recomputation."""

    def __init__(
        self,
        *,
        grid_path: Path | str = DEFAULT_DATABASE_PATH,
        weather_source: StoredWeatherFeatures | None = None,
        firms_path: Path | str = FIRMS_INPUT,
        firms_index: PriorFirmsIndex | None = None,
        maximum_cell_distance_km: float = 5.0,
    ):
        self.grid_path = Path(grid_path)
        self.weather_source = weather_source or StoredWeatherFeatures()
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
        try:
            weather = self.weather_source.features_for_cell(cell["cell_id"], evaluation)
        except SQLAlchemyError:
            return {"status": "unavailable", "reason": "weather_history_unavailable", "features": None, "cell_id": cell["cell_id"]}
        if weather["status"] != "success":
            return {
                "status": "unavailable", "reason": weather.get("reason", "weather_history_incomplete"),
                "features": None, "cell_id": cell["cell_id"],
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
            "cell_id": cell["cell_id"],
            "evaluation_time": evaluation.isoformat().replace("+00:00", "Z"),
        }
