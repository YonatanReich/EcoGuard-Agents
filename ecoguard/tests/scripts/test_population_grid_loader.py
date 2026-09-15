"""Coarsening sums people; it must never average them.

A 200 m cell built from four 100 m pixels holds the sum of their four
populations. Getting that wrong divides the national total by the square of the
coarsen factor and still produces a plausible-looking map, which is exactly the
kind of error that survives to a demo.

The ragged edge is tested too: Israel's raster is not a whole number of
coarsened cells wide, so the last column group is narrower than the rest and
must still carry its people rather than be dropped or double-counted.
"""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ecoguard.scripts.load_population_grid import cells_from_raster

# 1 degree pixels starting at (30 E, 40 N) — nothing to do with Israel, but a
# grid whose corners are whole numbers is readable in an assertion.
ORIGIN_X, ORIGIN_Y, PIXEL = 30.0, 40.0, 1.0


def _raster(tmp_path, values, crs="EPSG:4326"):
    array = np.array(values, dtype="float32")
    path = tmp_path / "population.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(ORIGIN_X, ORIGIN_Y, PIXEL, PIXEL),
        nodata=-99999.0,
    ) as destination:
        destination.write(array, 1)
    return path


def test_every_populated_pixel_becomes_one_cell(tmp_path):
    path = _raster(tmp_path, [[5.0, 0.0], [0.0, 7.0]])

    cells = list(cells_from_raster(path, coarsen=1))

    assert [cell["population"] for cell in cells] == [5.0, 7.0]
    # Top-left pixel: one degree east and one degree south of the origin.
    assert cells[0] == pytest.approx(
        {"west": 30.0, "south": 39.0, "east": 31.0, "north": 40.0, "population": 5.0}
    )


def test_coarsening_sums_the_pixels_it_merges(tmp_path):
    path = _raster(tmp_path, [[1.0, 2.0], [3.0, 4.0]])

    cells = list(cells_from_raster(path, coarsen=2))

    assert len(cells) == 1
    assert cells[0]["population"] == pytest.approx(10.0)
    assert (cells[0]["west"], cells[0]["north"]) == (30.0, 40.0)
    assert (cells[0]["east"], cells[0]["south"]) == (32.0, 38.0)


def test_a_ragged_final_group_keeps_its_people(tmp_path):
    path = _raster(tmp_path, [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]])

    cells = list(cells_from_raster(path, coarsen=2))

    # Nine pixels of one person each, in four unequal cells: 2x2, 2x1, 1x2, 1x1.
    assert sorted(cell["population"] for cell in cells) == [1.0, 2.0, 2.0, 4.0]
    assert sum(cell["population"] for cell in cells) == 9.0


def test_nodata_is_not_counted_as_people(tmp_path):
    path = _raster(tmp_path, [[-99999.0, 4.0], [np.nan, -1.0]])

    cells = list(cells_from_raster(path, coarsen=1))

    assert [cell["population"] for cell in cells] == [4.0]


def test_a_raster_in_the_wrong_projection_is_refused(tmp_path):
    path = _raster(tmp_path, [[1.0]], crs="EPSG:3857")

    with pytest.raises(SystemExit):
        list(cells_from_raster(path, coarsen=1))
