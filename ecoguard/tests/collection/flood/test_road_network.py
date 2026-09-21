"""Road-layer normalization for Flood response-site discovery."""

from datetime import datetime, timezone

from ecoguard.collection.flood.road_network import (
    normalize_road_class,
    road_records,
    vehicle_access,
)


NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def test_osm_highway_values_are_normalized_to_mapbox_classes():
    assert normalize_road_class({"highway": "motorway_link"}) == "motorway_link"
    assert normalize_road_class({"highway": "residential"}) == "street"
    assert normalize_road_class({"highway": "footway"}) == "path"


def test_explicit_mapbox_class_takes_precedence():
    assert (
        normalize_road_class({"class": "street_limited", "highway": "residential"})
        == "street_limited"
    )


def test_emergency_access_overrides_general_vehicle_prohibition():
    assert vehicle_access({"access": "no", "emergency": "yes"}) is True
    assert vehicle_access({"motor_vehicle": "no"}) is False
    assert vehicle_access({}) is None


def test_only_supported_line_features_become_rows():
    rows = road_records(
        [
            {
                "type": "Feature",
                "id": "way/1",
                "properties": {
                    "highway": "primary",
                    "name:he": "כביש ראשי",
                    "ref": "1",
                    "bridge": "yes",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[34.8, 32.0], [34.9, 32.1]],
                },
            },
            {
                "type": "Feature",
                "id": "poi/2",
                "properties": {"highway": "primary"},
                "geometry": {"type": "Point", "coordinates": [34.8, 32.0]},
            },
        ],
        source="osm-test",
        imported_at=NOW,
    )

    assert len(rows) == 1
    assert rows[0]["source_feature_id"] == "way/1"
    assert rows[0]["road_class"] == "primary"
    assert rows[0]["road_ref"] == "1"
    assert rows[0]["bridge"] is True
