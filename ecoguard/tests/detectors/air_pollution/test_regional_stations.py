from ecoguard.detectors.air_pollution.regional_stations import (
    DESIGNATED_STATIONS,
    REGIONS,
    anchor_cell,
    region_of,
)
from ecoguard.shared.cells import are_adjacent


def test_at_most_two_stations_per_region_and_none_twice():
    stations = [sid for _, _, members in REGIONS.values() for sid, _ in members]
    assert all(1 <= len(members) <= 2 for _, _, members in REGIONS.values())
    assert len(stations) == len(set(stations)) == len(DESIGNATED_STATIONS)


def test_a_regions_stations_share_one_anchor_so_they_are_one_card():
    # Gush Dan: University and Lehi Street are 8 km apart, two different cells.
    assert anchor_cell("39") == anchor_cell("2")
    assert region_of("2") == "גוש דן"
    assert anchor_cell("96") is None  # Check Post, Haifa: real, not designated


def test_two_regions_never_share_an_anchor():
    anchors = [anchor for _, anchor, _ in REGIONS.values()]
    assert len(anchors) == len(set(anchors))
