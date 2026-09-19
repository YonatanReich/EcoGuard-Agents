"""Station matching and full downstream-chain behavior."""

from ecoguard.detectors.flood.topology import (
    build_downstream_route,
    build_stream_context,
)


def _node(water_source_id, downstream_id):
    return {
        "water_source_id": water_source_id,
        "name_he": f"נחל {water_source_id}",
        "object_ids": [water_source_id],
        "feature_count": 1,
        "main_catchment_code": "12",
        "main_catchment_name": "אגן בדיקה",
        "draining_water_id": downstream_id,
        "draining_water_name": (
            f"נחל {downstream_id}" if downstream_id is not None else None
        ),
        "representative_location": {
            "latitude": 32.0,
            "longitude": 34.8,
        },
        "topology_conflict": False,
    }


def test_station_match_produces_the_complete_declared_downstream_chain():
    station = {
        "station_name_he": "תחנת נחל בדיקה",
        "station_name_en": "Test gauge",
        "latitude": 32.0,
        "longitude": 34.8,
        "basin_id": 12,
    }
    stream_context = build_stream_context(
        station,
        [
            {
                "stream_id": 21,
                "object_id": 301,
                "name_he": "נחל בדיקה",
                "water_source_id": 9001,
                "main_catchment_code": "12",
                "main_catchment_name": "אגן בדיקה",
                "draining_water_id": 9002,
                "draining_water_name": "נחל 9002",
                "distance_m": 18.4,
            }
        ],
    )
    network = {
        9001: _node(9001, 9002),
        9002: _node(9002, 9003),
        9003: _node(9003, None),
    }

    route = build_downstream_route(stream_context, network)

    assert stream_context["matched"] is True
    assert route["status"] == "complete"
    assert route["termination"] == "declared_network_end"
    assert [item["water_source_id"] for item in route["segments"]] == [
        9001,
        9002,
        9003,
    ]


def test_downstream_route_stops_safely_when_the_provider_graph_has_a_cycle():
    stream_context = {
        "matched": True,
        "confidence": "high",
        "stream": {"water_source_id": 1, "object_id": 10},
    }

    route = build_downstream_route(
        stream_context,
        {1: _node(1, 2), 2: _node(2, 1)},
    )

    assert route["status"] == "partial"
    assert route["termination"] == "cycle_detected"
    assert route["confidence"] == "low"
