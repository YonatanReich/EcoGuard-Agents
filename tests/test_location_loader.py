"""
Tests for the Israel locations loader.
"""

from utils.location_loader import load_israel_locations


def test_load_israel_locations_returns_enabled_locations():
    locations = load_israel_locations()

    assert len(locations) == 10

    first_location = locations[0]

    assert first_location["name"] == "Givat Shmuel"
    assert first_location["region_type"] == "city"
    assert first_location["latitude"] == 32.0786
    assert first_location["longitude"] == 34.8483
    assert first_location["scan_radius_km"] == 2
    assert first_location["enabled"] is True


def test_all_locations_have_required_fields():
    locations = load_israel_locations()

    required_fields = [
        "name",
        "region_type",
        "latitude",
        "longitude",
        "scan_radius_km",
        "enabled",
    ]

    for location in locations:
        for field in required_fields:
            assert field in location