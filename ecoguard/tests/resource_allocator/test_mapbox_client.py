import httpx
import pytest

from ecoguard.resource_allocator.mapbox_client import MapboxClient, RoutingError


def client_for(handler, **options):
    return MapboxClient(
        access_token="test-token",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        **options,
    )


def test_matrix_is_chunked_and_uses_one_event_destination():
    calls = []

    def handler(request):
        coordinates = request.url.path.rsplit("/", 1)[-1].split(";")
        source_indices = request.url.params["sources"].split(";")
        destination_index = request.url.params["destinations"]
        calls.append(
            {
                "coordinate_count": len(coordinates),
                "sources": source_indices,
                "destination": destination_index,
            }
        )
        durations = [[100 + index] for index in range(len(source_indices))]
        distances = [[1000 + index] for index in range(len(source_indices))]
        if len(calls) == 1:
            durations[1] = [None]
            distances[1] = [None]
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "durations": durations,
                "distances": distances,
                "sources": [
                    {"location": [35.0, 31.0], "distance": 5}
                    for _ in source_indices
                ],
                "destinations": [
                    {
                        "location": [35.5, 31.5],
                        "distance": 20,
                        "name": "Event road",
                    }
                ],
            },
        )

    stations = [
        {"latitude": 31.0 + index / 100, "longitude": 35.0}
        for index in range(3)
    ]
    event = {"latitude": 31.5, "longitude": 35.5}

    result = client_for(handler, matrix_max_sources=2).travel_metrics(
        stations,
        event,
    )

    assert calls == [
        {"coordinate_count": 3, "sources": ["0", "1"], "destination": "2"},
        {"coordinate_count": 2, "sources": ["0", "1"], "destination": "1"},
    ]
    assert result["metrics"][0]["duration_s"] == 100
    assert result["metrics"][1] is None
    assert result["metrics"][2]["distance_m"] == 1000
    assert result["road_access"]["snap_distance_m"] == 20
    assert result["road_access"]["snapped_location"] == event


def test_directions_returns_geojson_native_hebrew_and_offroad_segment():
    def handler(request):
        assert request.url.path.startswith(
            "/directions/v5/mapbox/driving-traffic/"
        )
        assert request.url.params["steps"] == "true"
        assert request.url.params["language"] == "he"
        assert request.url.params["geometries"] == "geojson"
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "waypoints": [
                    {"location": [35.0, 31.0], "distance": 12},
                    {
                        "location": [35.1, 31.1],
                        "distance": 5000,
                        "name": "Last road",
                    },
                ],
                "routes": [
                    {
                        "distance": 15000,
                        "duration": 900,
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[35.0, 31.0], [35.1, 31.1]],
                        },
                        "legs": [
                            {
                                "steps": [
                                    {
                                        "distance": 500,
                                        "duration": 60,
                                        "name": "כביש 1",
                                        "maneuver": {
                                            "type": "turn",
                                            "modifier": "left",
                                            "instruction": "פנו שמאלה אל כביש 1",
                                        },
                                    }
                                ]
                            }
                        ],
                    }
                ],
            },
        )

    route = client_for(handler, event_road_tolerance_m=100).route(
        {"latitude": 31.0, "longitude": 35.0},
        {"latitude": 31.14, "longitude": 35.14},
    )

    assert route["provider"] == "mapbox"
    assert route["status"] == "partial_offroad"
    assert route["distance_m"] == 15000
    assert route["duration_s"] == 900
    assert route["geometry"]["type"] == "LineString"
    assert route["steps_he"][0]["instruction"] == "פנו שמאלה אל כביש 1"
    assert route["offroad_segment"]["distance_m"] == 5000
    assert route["offroad_segment"]["geometry"]["coordinates"] == [
        [35.1, 31.1],
        [35.14, 31.14],
    ]


def test_missing_token_fails_without_making_a_request():
    client = MapboxClient(access_token=None)
    client.access_token = None

    with pytest.raises(RoutingError, match="MAPBOX_ACCESS_TOKEN"):
        client.travel_metrics(
            [{"latitude": 31.0, "longitude": 35.0}],
            {"latitude": 31.1, "longitude": 35.1},
        )


def test_mapbox_error_does_not_expose_access_token():
    def handler(request):
        return httpx.Response(
            401,
            json={"code": "Unauthorized", "message": "Not Authorized"},
        )

    with pytest.raises(RoutingError) as error:
        client_for(handler).travel_metrics(
            [{"latitude": 31.0, "longitude": 35.0}],
            {"latitude": 31.1, "longitude": 35.1},
        )

    assert "test-token" not in str(error.value)


def test_tilequery_verifies_local_crossing_and_returns_mapbox_access_point():
    def handler(request):
        assert request.url.path.startswith(
            "/v4/mapbox.mapbox-streets-v8/tilequery/34.8,32.0.json"
        )
        assert request.url.params["layers"] == "road"
        assert request.url.params["geometry"] == "linestring"
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": 77,
                        "geometry": {
                            "type": "Point",
                            "coordinates": [34.8001, 32.0001],
                        },
                        "properties": {
                            "class": "primary",
                            "name_he": "כביש 1",
                            "ref": "1",
                            "tilequery": {
                                "distance": 14.0,
                                "geometry": "linestring",
                                "layer": "road",
                            },
                        },
                    }
                ],
            },
        )

    result = client_for(handler).verify_road_candidate(
        {
            "latitude": 32.0,
            "longitude": 34.8,
            "road_class": "primary_link",
            "road_name": "כביש 1",
            "road_ref": "1",
        }
    )

    assert result["verified"] is True
    assert result["confidence"] == "high"
    assert result["mapbox_snap_distance_m"] == 14.0
    assert result["mapbox_access_location"] == {
        "latitude": 32.0001,
        "longitude": 34.8001,
    }


def test_tilequery_rejects_a_conflicting_explicit_road_number():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": 77,
                        "geometry": {
                            "type": "Point",
                            "coordinates": [34.8, 32.0],
                        },
                        "properties": {
                            "class": "primary",
                            "ref": "4",
                            "tilequery": {
                                "distance": 0,
                                "geometry": "linestring",
                                "layer": "road",
                            },
                        },
                    }
                ],
            },
        )

    result = client_for(handler).verify_road_candidate(
        {
            "latitude": 32.0,
            "longitude": 34.8,
            "road_class": "primary",
            "road_ref": "1",
        }
    )

    assert result["verified"] is False
    assert result["reason"] == "compatible_mapbox_road_not_found"
