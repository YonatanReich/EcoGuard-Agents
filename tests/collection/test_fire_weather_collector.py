"""One raster is sampled per cell; the pixel maths is the part that can be wrong."""

from PIL import Image

from ecoguard.collection.base import service_area_cells
from ecoguard.collection.fire_weather import FireWeatherCollector, area_bounds, pixel_for

HIGH_DANGER_RGB = (230, 172, 0)
NO_DATA_RGB = (0, 0, 0)


def test_the_north_west_corner_is_the_top_left_pixel():
    bounds = (34.0, 29.0, 36.0, 33.0)
    assert pixel_for(33.0, 34.0, bounds, (100, 200)) == (0, 0)
    assert pixel_for(29.0, 36.0, bounds, (100, 200)) == (99, 199)
    assert pixel_for(31.0, 35.0, bounds, (100, 200)) == (50, 100)


def test_every_cell_is_sampled_from_a_single_raster():
    bounds = area_bounds()
    height = round(512 * (bounds[3] - bounds[1]) / (bounds[2] - bounds[0]))
    raster = Image.new("RGB", (512, height), HIGH_DANGER_RGB)
    calls = []

    collector = FireWeatherCollector()
    collector.fetch_area_raster = lambda b, day: (calls.append(day), raster)[1]

    records = collector.fetch()

    assert len(calls) == 1
    assert len(records) == len(service_area_cells())
    assert records[0]["payload"]["danger_level"] == "high"
    # FWI is a daily product, so every cell shares one midnight-UTC timestamp.
    assert {record["observed_at"].hour for record in records} == {0}


def test_unclassified_pixels_are_skipped_rather_than_stored_as_unknown():
    raster = Image.new("RGB", (512, 1200), NO_DATA_RGB)
    collector = FireWeatherCollector()
    collector.fetch_area_raster = lambda bounds, day: raster

    assert collector.fetch() == []
