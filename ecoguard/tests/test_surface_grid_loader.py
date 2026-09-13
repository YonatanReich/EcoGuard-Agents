"""Slope must survive coarsening, and cover fractions must survive mixing.

Four ways to get the static grid silently wrong and still draw a plausible map.

Computing slope after averaging the DEM: a 270 m cell built from an averaged
surface reads flat where the ground is a gully, and every fire in it is
modelled as a slow creep. Getting aspect backwards: aspect is the bearing the
ground *faces*, which is downhill, while fire runs the other way, so a sign
error sends every predicted fire down the mountain. Reducing land cover to a
dominant label: the mixture of scrub and houses is the wildland-urban
interface, and a label calls it "shrubland" and loses the houses. And losing
pixels between the two grids, which would leave fractions that quietly fail to
sum to one.

The terrain cases run on ramps whose true slope is arithmetic, so the
assertions read as geometry rather than as recorded output.
"""

import math

import numpy as np
import pytest
from rasterio.transform import from_origin

from ecoguard.database.repositories.surface import (
    BURNABLE_COLUMNS,
    COVER_COLUMNS,
    bearing_degrees,
    shape_fuel,
)
from scripts.load_surface_grid import (
    COVER_CODES,
    required_cover_tiles,
    required_dem_tiles,
    slope_aspect,
    surface_cells,
    terrain_blocks,
)

# One metre per pixel of ground, so a rise of 1 per pixel is exactly 45 degrees.
METRES = 1.0
TRANSFORM = from_origin(35.0, 32.0, 0.001, 0.001)


def _ramp(values):
    return np.array(values, dtype="float32")


def _cells(elevation, valid, coarsen, cover=None):
    """Run the full block-reduce and emit, with land cover stubbed flat."""
    terrain = terrain_blocks(elevation, valid, TRANSFORM, coarsen)
    if cover is None:
        cover = np.zeros((*terrain["count"].shape, len(COVER_COLUMNS)), dtype="float32")
    return list(surface_cells(terrain, cover, TRANSFORM, coarsen, elevation.shape))


def test_a_ramp_rising_eastwards_faces_west():
    # Row 0 is north; every row climbs 1 m per pixel towards the east.
    slope, aspect = slope_aspect(_ramp([[0.0, 1.0, 2.0]] * 3), METRES, METRES)

    # The centre pixel is the only one with a full neighbourhood.
    assert slope[1, 1] == pytest.approx(45.0)
    # Uphill is east, so the ground faces west and a fire runs east.
    assert aspect[1, 1] == pytest.approx(270.0)


def test_a_ramp_rising_northwards_faces_south():
    slope, aspect = slope_aspect(_ramp([[2.0] * 3, [1.0] * 3, [0.0] * 3]), METRES, METRES)

    assert slope[1, 1] == pytest.approx(45.0)
    assert aspect[1, 1] == pytest.approx(180.0)


def test_flat_ground_is_zero_slope():
    slope, _ = slope_aspect(_ramp([[7.0] * 3] * 3), METRES, METRES)

    assert slope[1, 1] == pytest.approx(0.0)


def test_a_steep_face_is_not_averaged_away():
    # A cliff down one column of an otherwise flat 3x3: the mean slope of the
    # coarsened cell is mild, but the steepest pixel in it is not, and that is
    # the pixel a fire accelerates on.
    elevation = _ramp([[0.0, 0.0, 300.0]] * 3)

    cell = _cells(elevation, np.ones(elevation.shape, dtype=bool), 3)[0]

    assert cell["slope_max_deg"] > cell["slope_deg"]
    assert cell["slope_max_deg"] > 45.0


def test_cells_outside_the_service_area_are_not_emitted():
    elevation = _ramp([[0.0, 1.0], [2.0, 3.0]])

    assert _cells(elevation, np.zeros(elevation.shape, dtype=bool), 1) == []


def test_a_cell_covers_the_pixels_it_merged():
    elevation = _ramp([[10.0, 10.0], [10.0, 10.0]])

    cell = _cells(elevation, np.ones(elevation.shape, dtype=bool), 2)[0]

    assert (cell["west"], cell["north"]) == pytest.approx((35.0, 32.0))
    assert (cell["east"], cell["south"]) == pytest.approx((35.002, 31.998))
    assert cell["elevation_m"] == pytest.approx(10.0)
    # Uniform height in every direction: no slope, therefore no aspect at all
    # rather than a bearing invented out of rounding noise.
    assert cell["aspect_deg"] is None


def test_a_ragged_final_block_still_becomes_a_cell():
    elevation = _ramp([[1.0] * 3] * 3)

    # Nine pixels in four unequal blocks: 2x2, 2x1, 1x2, 1x1.
    assert len(_cells(elevation, np.ones(elevation.shape, dtype=bool), 2)) == 4


def test_israel_needs_the_tiles_that_cover_it():
    dem = required_dem_tiles((34.2, 29.4, 35.9, 33.4))
    cover = required_cover_tiles((34.2, 29.4, 35.9, 33.4))

    # GLO-90 is one degree a tile, WorldCover three.
    assert len(dem) == 10
    assert any("N31_00_E035_00" in filename for filename, _ in dem)
    assert all(url.startswith("https://copernicus-dem-90m.s3") for _, url in dem)

    assert len(cover) == 3
    assert {filename for filename, _ in cover} == {
        "ESA_WorldCover_10m_2021_v200_N27E033_Map.tif",
        "ESA_WorldCover_10m_2021_v200_N30E033_Map.tif",
        "ESA_WorldCover_10m_2021_v200_N33E033_Map.tif",
    }


def test_aspect_of_a_coarsened_slope_matches_its_pixels():
    # Eastward ramp again, this time reduced to a single cell: the block's
    # bearing must be the bearing of the pixels inside it, not an average of
    # numbers that happens to land elsewhere.
    elevation = _ramp([[float(column) for column in range(3)] for _ in range(3)])

    cell = _cells(elevation, np.ones(elevation.shape, dtype=bool), 3)[0]

    assert cell["aspect_deg"] == pytest.approx(270.0, abs=1.0)


def test_vector_aspect_does_not_average_north_into_south():
    # The failure a plain numeric mean produces: 350 and 10 degrees are both
    # north-facing, and their arithmetic mean is due south.
    east = math.sin(math.radians(350)) + math.sin(math.radians(10))
    north = math.cos(math.radians(350)) + math.cos(math.radians(10))

    # Due north, and reported as 0 rather than 360: atan2 returns a hair below
    # zero here, and a bare modulo would wrap it to the top of the range.
    assert bearing_degrees(east, north) == 0.0


def test_every_cover_column_has_a_code_except_the_remainder():
    # unmapped is the only column without a WorldCover class behind it. If that
    # stops being true the fractions stop summing to one.
    assert COVER_COLUMNS[-1] == "unmapped"
    assert len(COVER_CODES) == len(COVER_COLUMNS) - 1


def test_cover_fractions_reach_the_row_they_describe():
    elevation = _ramp([[10.0, 10.0], [10.0, 10.0]])
    terrain = terrain_blocks(elevation, np.ones(elevation.shape, dtype=bool), TRANSFORM, 2)
    cover = np.zeros((*terrain["count"].shape, len(COVER_COLUMNS)), dtype="float32")
    cover[0, 0, COVER_COLUMNS.index("shrubland")] = 0.6
    cover[0, 0, COVER_COLUMNS.index("built_up")] = 0.4

    cell = list(surface_cells(terrain, cover, TRANSFORM, 2, elevation.shape))[0]

    assert cell["shrubland"] == pytest.approx(0.6)
    assert cell["built_up"] == pytest.approx(0.4)
    assert cell["tree_cover"] == pytest.approx(0.0)


def test_a_mismatched_cover_grid_is_refused_rather_than_misaligned():
    elevation = _ramp([[10.0, 10.0], [10.0, 10.0]])
    terrain = terrain_blocks(elevation, np.ones(elevation.shape, dtype=bool), TRANSFORM, 2)
    wrong = np.zeros((5, 5, len(COVER_COLUMNS)), dtype="float32")

    with pytest.raises(SystemExit):
        list(surface_cells(terrain, wrong, TRANSFORM, 2, elevation.shape))


def test_the_wildland_urban_interface_keeps_both_halves():
    # The mixture a dominant label would destroy: mostly scrub, but a third of
    # it is houses, and the houses are the reason anyone is reading this.
    row = {"cell_count": 40, **{column: 0.0 for column in COVER_COLUMNS}}
    row.update(shrubland=0.55, built_up=0.33, bare_sparse_vegetation=0.12)

    fuel = shape_fuel(row)

    assert fuel["dominant"] == "shrubland"
    assert fuel["built_up_fraction"] == pytest.approx(0.33)
    # Burnable is the wildland fuel only. A town burns, but not as a meadow.
    assert fuel["burnable_fraction"] == pytest.approx(0.55)
    assert "tree_cover" not in fuel["fractions"]


def test_burnable_never_counts_the_built_up_fraction():
    assert "built_up" not in BURNABLE_COLUMNS


def test_no_cells_means_nulls_rather_than_a_confident_zero():
    fuel = shape_fuel({"cell_count": 0, **{column: None for column in COVER_COLUMNS}})

    assert fuel == {
        "dominant": None,
        "burnable_fraction": None,
        "built_up_fraction": None,
        "fractions": {},
        "cell_count": 0,
    }
