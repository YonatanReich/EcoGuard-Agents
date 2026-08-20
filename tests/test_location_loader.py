"""
Tests for the Israel locations loader.

Verifies that data/israel_locations.json parses, that the enabled-filter
works, and that every record carries the fields the collection service reads.

These assert against the real data file rather than a fixture, so they double
as a guard on that file's contents: adding, removing or disabling a location
will change the expected count.

The loader uses a path relative to the working directory, so run pytest from
the repository root.
"""

from utils.location_loader import load_israel_locations


def test_load_israel_locations_returns_enabled_locations():
    """All ten configured locations load, and the first parses correctly.

    Spot-checks Givat Shmuel field by field to confirm types survive the JSON
    round trip — coordinates as floats, enabled as a real bool rather than a
    string.
    """
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
    """No location is missing a field the collection service depends on.

    MultiLocationCollectionService reads these keys per location; a missing
    one would surface as a silent None passed to an agent rather than a clear
    error, so it is worth catching here.
    """
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