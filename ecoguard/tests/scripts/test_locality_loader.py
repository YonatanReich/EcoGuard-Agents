import pytest

from ecoguard.scripts.load_localities import parse_feature_collection


def _payload(geometry_type="Polygon"):
    coordinates = (
        [[[34.7, 32.0], [34.8, 32.0], [34.8, 32.1], [34.7, 32.0]]]
        if geometry_type == "Polygon"
        else [[[[34.7, 32.0], [34.8, 32.0], [34.8, 32.1], [34.7, 32.0]]]]
    )
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "code": "5000",
                "hebrew": "תל אביב-יפו",
                "english": "Tel Aviv-Yafo",
                "kind": "municipality",
            },
            "geometry": {"type": geometry_type, "coordinates": coordinates},
        }],
    }


def _parse(payload):
    return parse_feature_collection(
        payload,
        code_field="code",
        name_he_field="hebrew",
        name_en_field="english",
        type_field="kind",
        resource_id_field="resource_id",
    )


@pytest.mark.parametrize("geometry_type", ["Polygon", "MultiPolygon"])
def test_loader_accepts_only_named_polygonal_localities(geometry_type):
    row = _parse(_payload(geometry_type))[0]

    assert row.locality_code == "5000"
    assert row.name_he == "תל אביב-יפו"
    assert f'"type": "{geometry_type}"' in row.geometry_json


def test_loader_rejects_non_polygon_and_duplicate_codes_before_writing():
    point = _payload()
    point["features"][0]["geometry"] = {
        "type": "Point",
        "coordinates": [34.8, 32.1],
    }
    with pytest.raises(ValueError, match="non_polygon_geometry"):
        _parse(point)

    duplicate = _payload()
    duplicate["features"].append(dict(duplicate["features"][0]))
    with pytest.raises(ValueError, match="duplicate_locality_code"):
        _parse(duplicate)
