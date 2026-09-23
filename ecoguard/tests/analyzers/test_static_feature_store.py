from __future__ import annotations

import sqlite3

import pytest
from rasterio.transform import from_origin

from ecoguard.analyzers.fire.ml.build_historical_landcover_terrain_features import LAND_COVER_FEATURES, slope_from_neighborhood
from ecoguard.shared.grid import generate_grid
from ecoguard.analyzers.fire.static_feature_store import (
    STATIC_MODEL_FEATURES,
    StaticSample,
    build_static_grid_database,
    select_representative_land_pixel,
)
from ecoguard.analyzers.fire.ml.train_fire_prediction_landcover_terrain_models import FULL_FEATURES


class FakeSampler:
    def __init__(self, samples=None):
        self.samples = samples or {}
        self.closed = False

    def sample(self, latitude, longitude):
        return self.samples.get((latitude, longitude), StaticSample(120.0, 4.5, 30))

    def close(self):
        self.closed = True


def test_grid_is_deterministic_and_cell_ids_are_unique():
    bounds = (34.0, 31.0, 34.2, 31.2)
    first = generate_grid(bounds)
    second = generate_grid(bounds)
    assert first == second
    assert len({cell.cell_id for cell in first}) == len(first)


def test_grid_spacing_is_approximately_five_km():
    cells = generate_grid((34.0, 31.0, 34.2, 31.2))
    first_column = [cell for cell in cells if cell.grid_col == 0]
    assert (first_column[1].latitude - first_column[0].latitude) * 110.574 == pytest.approx(5.0, abs=0.001)
    first_row = [cell for cell in cells if cell.grid_row == 0]
    longitude_km = (first_row[1].longitude - first_row[0].longitude) * 111.320
    assert 4.0 < longitude_km < 6.0  # longitude correction is latitude-dependent


def test_database_persists_exact_static_schema_and_one_hot(tmp_path):
    path = tmp_path / "grid.sqlite"
    summary = build_static_grid_database(path, sampler=FakeSampler(), bounds=(34.0, 31.0, 34.06, 31.06), built_at="2026-01-01T00:00:00Z")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    row = connection.execute("SELECT * FROM risk_grid_cells LIMIT 1").fetchone()
    names = {item[1] for item in connection.execute("PRAGMA table_info(risk_grid_cells)")}
    connection.close()
    assert set(STATIC_MODEL_FEATURES) <= names
    assert sum(row[name] for name in LAND_COVER_FEATURES) == 1
    assert row["land_cover_grassland"] == 1
    assert summary["complete_cells"] == summary["active_cells"]


def test_static_feature_names_match_current_model_schema():
    assert set(STATIC_MODEL_FEATURES).issubset(FULL_FEATURES)


def test_water_and_unmapped_cells_are_inactive(tmp_path):
    cells = generate_grid((34.0, 31.0, 34.15, 31.06))
    samples = {
        (cells[0].latitude, cells[0].longitude): StaticSample(None, None, 80),
        (cells[1].latitude, cells[1].longitude): StaticSample(None, None, None),
    }
    path = tmp_path / "grid.sqlite"
    build_static_grid_database(path, sampler=FakeSampler(samples), bounds=(34.0, 31.0, 34.15, 31.06))
    connection = sqlite3.connect(path)
    statuses = connection.execute("SELECT active, feature_status FROM risk_grid_cells ORDER BY grid_col").fetchall()
    connection.close()
    assert statuses[0] == (0, "inactive_water")
    assert statuses[1] == (0, "inactive_unmapped")


def test_slope_calculation_reuses_horn_helper():
    numpy = pytest.importorskip("numpy")
    values = numpy.array([[0, 1, 2], [0, 1, 2], [0, 1, 2]], dtype=float)
    assert slope_from_neighborhood(values, 90, 90) is not None


def test_land_overlap_recovery_rejects_less_than_twenty_percent():
    numpy = pytest.importorskip("numpy")
    values = numpy.full((10, 10), 80, dtype=numpy.uint8)
    values[0, :] = 40
    values[1, :9] = 40
    mask = numpy.ones_like(values, dtype=bool)
    assert select_representative_land_pixel(values, mask, from_origin(0, 10, 1, 1), 5, 5) is None


def test_coastal_recovery_requires_ninety_percent_of_land_inside_service_area():
    numpy = pytest.importorskip("numpy")
    values = numpy.full((10, 10), 80, dtype=numpy.uint8)
    values[:3, :] = 40
    mask = numpy.zeros_like(values, dtype=bool)
    mask[:2, :] = True
    assert select_representative_land_pixel(values, mask, from_origin(0, 10, 1, 1), 5, 5) is None


def test_coastal_water_centroid_with_twenty_percent_land_and_ninety_percent_inside_is_recovered():
    numpy = pytest.importorskip("numpy")
    values = numpy.full((10, 10), 80, dtype=numpy.uint8)
    values[:2, :] = 40
    mask = numpy.ones_like(values, dtype=bool)
    assert select_representative_land_pixel(values, mask, from_origin(0, 10, 1, 1), 5, 5) is not None


def test_water_centroid_with_sufficient_land_gets_deterministic_representative():
    numpy = pytest.importorskip("numpy")
    values = numpy.full((10, 10), 80, dtype=numpy.uint8)
    values[:6, :] = 40
    values[:3, :3] = 50
    mask = numpy.ones_like(values, dtype=bool)
    first = select_representative_land_pixel(values, mask, from_origin(0, 10, 1, 1), 5, 5)
    second = select_representative_land_pixel(values, mask, from_origin(0, 10, 1, 1), 5, 5)
    assert first == second
    assert first is not None and first[0] == 40


def test_ashkelon_style_water_centroid_is_recoverable_when_cell_is_overwhelmingly_land():
    numpy = pytest.importorskip("numpy")
    values = numpy.full((100, 100), 40, dtype=numpy.uint8)
    values[50, 50] = 80
    mask = numpy.ones_like(values, dtype=bool)
    recovered = select_representative_land_pixel(values, mask, from_origin(0, 100, 1, 1), 49.5, 50.5)
    assert recovered is not None
    assert recovered[0] == 40


def test_activation_provenance_is_persisted(tmp_path):
    path = tmp_path / "grid.sqlite"
    build_static_grid_database(path, sampler=FakeSampler(), bounds=(34.0, 31.0, 34.06, 31.06))
    connection = sqlite3.connect(path)
    method = connection.execute("SELECT activation_method FROM risk_grid_cells").fetchone()[0]
    connection.close()
    assert method == "centroid_land"


def test_builder_has_no_model_or_network_coupling(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network/model access is not allowed")
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    path = tmp_path / "grid.sqlite"
    build_static_grid_database(path, sampler=FakeSampler(), bounds=(34.0, 31.0, 34.06, 31.06))
    assert path.exists()
