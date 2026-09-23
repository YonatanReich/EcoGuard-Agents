"""cell_for inverts the grid, so it has to agree with the grid it inverts."""

import pytest

from ecoguard.collectors.base import cell_for, service_area_cells


def test_every_service_area_centroid_maps_back_to_its_own_cell():
    for cell in service_area_cells():
        assert cell_for(cell.latitude, cell.longitude) == cell.cell_id


def test_a_point_offset_within_a_cell_still_lands_in_it():
    cell = service_area_cells()[len(service_area_cells()) // 2]
    # 500 m north-east of the centroid is well inside a 5 km cell.
    assert cell_for(cell.latitude + 0.004, cell.longitude + 0.004) == cell.cell_id


@pytest.mark.parametrize(
    "latitude,longitude",
    [
        (48.85, 2.35),    # Paris
        (31.5, 30.0),     # Mediterranean, west of the service area
        (25.0, 35.0),     # south of the grid entirely
    ],
)
def test_points_outside_the_service_area_have_no_cell(latitude, longitude):
    assert cell_for(latitude, longitude) is None
