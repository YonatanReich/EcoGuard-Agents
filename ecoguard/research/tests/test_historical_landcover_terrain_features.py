import json

import numpy as np
import rasterio
from rasterio.transform import from_origin

from research.datasets.build_historical_landcover_terrain_features import (
    DEM_VERSION, LAND_COVER_CLASSES, LAND_COVER_FEATURES, WORLDCOVER_VERSION,
    collect_static_features, enrich_rows, sample_land_cover, sample_slope,
    slope_from_neighborhood, sample_slope_across_tiles,
)


def source_row(identifier="x", latitude="31.9", longitude="34.9"):
    return {"sample_id": identifier, "latitude": latitude, "longitude": longitude, "fire_label": "0"}


def write_raster(path, values, *, west=34.0, north=32.0, pixel=.001):
    with rasterio.open(path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0], count=1, dtype=values.dtype, crs="EPSG:4326", transform=from_origin(west, north, pixel, pixel)) as dataset:
        dataset.write(values, 1)


def test_land_cover_class_and_encoding_are_deterministic(tmp_path):
    path = tmp_path / "land.tif"; write_raster(path, np.full((5, 5), 40, dtype="uint8"))
    with rasterio.open(path) as dataset: assert sample_land_cover(dataset, 31.9975, 34.0025) == 40
    cache = {"31.997500,34.002500": {"land_cover_code": 40, "land_cover_class": "cropland", "slope_degrees": 2.0}}
    first = enrich_rows([source_row(latitude="31.9975", longitude="34.0025")], cache)
    second = enrich_rows([source_row(latitude="31.9975", longitude="34.0025")], cache)
    assert first == second
    assert first[0]["land_cover_cropland"] == 1
    assert sum(first[0][field] for field in LAND_COVER_FEATURES) == 1


def test_slope_uses_three_by_three_neighborhood(tmp_path):
    flat = np.full((3, 3), 100.0)
    rising = np.array([[100, 110, 120], [100, 110, 120], [100, 110, 120]], dtype=float)
    assert slope_from_neighborhood(flat, 100, 100) == 0.0
    assert slope_from_neighborhood(rising, 100, 100) > 0
    path = tmp_path / "dem.tif"; write_raster(path, rising.astype("float32"), west=34, north=32, pixel=.001)
    with rasterio.open(path) as dataset: assert sample_slope(dataset, 31.9985, 34.0015) > 0


def test_slope_neighborhood_can_cross_tile_boundaries():
    class Pixel:
        transform = from_origin(34, 32, 1 / 1200, 1 / 1200)
        def index(self, longitude, latitude): return 0, 0
        def read(self, *_args, **_kwargs): return np.asarray([[100 + self.value]], dtype=float)
    calls = []
    def dataset_for(latitude, longitude):
        pixel = Pixel(); pixel.value = round((longitude - 35) * 100_000); calls.append((latitude, longitude)); return pixel
    assert sample_slope_across_tiles(32.0, 35.0, dataset_for) > 0
    assert len(calls) == 9


def test_static_features_work_without_settlement_metadata():
    row = source_row(); cache = {"31.900000,34.900000": {"land_cover_code": 30, "land_cover_class": "grassland", "slope_degrees": 4.5}}
    result = enrich_rows([row], cache)[0]
    assert "settlement" not in row
    assert result["land_cover_grassland"] == 1
    assert result["slope_degrees"] == 4.5


def test_all_6736_rows_are_preserved():
    rows = [source_row(str(index)) for index in range(6736)]
    cache = {"31.900000,34.900000": {"land_cover_code": 50, "land_cover_class": "built_up", "slope_degrees": 1.0}}
    output = enrich_rows(rows, cache)
    assert len(output) == 6736
    assert [row["sample_id"] for row in output] == [row["sample_id"] for row in rows]


def test_coordinate_cache_resume_has_no_provider_access(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"schema": 1, "worldcover": WORLDCOVER_VERSION, "dem": DEM_VERSION, "values": {"31.900000,34.900000": {"land_cover_code": 30, "land_cover_class": LAND_COVER_CLASSES[30], "slope_degrees": 3.0}}}), encoding="utf-8")
    class NoNetwork:
        def get(self, *_args, **_kwargs): raise AssertionError("cache hit attempted network")
    result = collect_static_features([source_row()], source_directory=tmp_path / "tiles", cache_path=cache_path, session=NoNetwork(), logger=lambda _: None)
    assert result["31.900000,34.900000"]["slope_degrees"] == 3.0
