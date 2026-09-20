"""Flood road selection policy, deduplication and Mapbox verification."""

from copy import deepcopy

import pytest

from ecoguard.resource_allocator.flood_road_targets import (
    FloodRoadTargetAgent,
    base_road_class,
    road_is_relevant,
)
from ecoguard.resource_allocator.mapbox_client import RoutingError


def candidate(
    road_class,
    *,
    feature_id="way/1",
    latitude=32.0,
    longitude=34.8,
    urban=False,
    road_ref="1",
    vehicle_access=None,
    distance=0,
):
    return {
        "road_segment_id": 1,
        "source": "osm-test",
        "source_feature_id": feature_id,
        "road_class": road_class,
        "road_name": "Test road",
        "road_ref": road_ref,
        "bridge": False,
        "tunnel": False,
        "vehicle_access": vehicle_access,
        "latitude": latitude,
        "longitude": longitude,
        "distance_from_station_m": distance,
        "urban": urban,
        "crossing_type": "at_grade",
    }


def incident(*, severity=4, precision=100):
    return {
        "id": "INC-20260920-0001",
        "signals": [
            {
                "hazard": "flood",
                "observed_at": "2026-09-20T08:00:00+00:00",
                "location": {
                    "latitude": 32.0,
                    "longitude": 34.8,
                    "precision_m": precision,
                },
                "evidence": {
                    "source_station_id": 50,
                    "severity_level": severity,
                },
            }
        ],
    }


class FakeRepository:
    def __init__(self, *, stream=None, crossings=None, nearby_by_radius=None):
        self.stream = stream
        self.crossings = list(crossings or [])
        self.nearby_by_radius = nearby_by_radius or {}
        self.calls = []

    def stream_identity(self, source_station_id):
        self.calls.append(("stream_identity", source_station_id))
        return deepcopy(self.stream)

    def stream_crossings(self, *, water_source_id, road_classes):
        self.calls.append(("stream_crossings", water_source_id, tuple(road_classes)))
        return deepcopy(self.crossings)

    def roads_near_station(self, *, source_station_id, radius_m, road_classes):
        self.calls.append(("roads_near_station", source_station_id, radius_m))
        return deepcopy(self.nearby_by_radius.get(radius_m, []))


class FakeMapbox:
    def __init__(self, *, fail=False, verified=True):
        self.fail = fail
        self.verified = verified
        self.calls = []

    def verify_road_candidate(self, road, *, radius_m):
        self.calls.append((deepcopy(road), radius_m))
        if self.fail:
            raise RoutingError("Mapbox unavailable")
        if not self.verified:
            return {
                "status": "unverified",
                "verified": False,
                "reason": "compatible_mapbox_road_not_found",
                "mapbox_access_location": None,
                "mapbox_snap_distance_m": None,
            }
        return {
            "status": "verified",
            "verified": True,
            "reason": None,
            "confidence": "high",
            "mapbox_access_location": {
                "latitude": road["latitude"] + 0.00001,
                "longitude": road["longitude"] + 0.00001,
            },
            "mapbox_snap_distance_m": 1.5,
            "mapbox_road_class": road["road_class"],
        }


@pytest.mark.parametrize(
    ("road_class", "urban", "severity", "access", "expected"),
    [
        ("motorway", False, 3, None, True),
        ("primary_link", False, 3, None, True),
        ("tertiary", False, 4, None, False),
        ("tertiary_link", True, 3, None, True),
        ("tertiary", False, 5, None, True),
        ("street", True, 3, None, True),
        ("street", True, 3, False, False),
        ("street", False, 6, None, False),
        ("street_limited", True, 3, None, True),
        ("street_limited", True, 3, False, False),
        ("service", True, 6, None, False),
        ("track", True, 6, None, False),
        ("pedestrian", True, 6, None, False),
    ],
)
def test_road_relevance_policy(road_class, urban, severity, access, expected):
    assert road_is_relevant(
        candidate(road_class, urban=urban, vehicle_access=access), severity
    ) is expected


def test_link_class_inherits_its_parent_class():
    assert base_road_class("motorway_link") == "motorway"
    assert base_road_class("tertiary_link") == "tertiary"
    assert base_road_class("street_limited") == "street_limited"


def test_matched_station_uses_only_its_water_source_geometry():
    repository = FakeRepository(
        stream={
            "stream_id": 701,
            "water_source_id": 9001,
            "stream_name": "נחל בדיקה",
            "match_confidence": "high",
            "has_geometry": True,
        },
        crossings=[candidate("primary")],
    )
    agent = FloodRoadTargetAgent(
        repository=repository,
        mapbox_client=FakeMapbox(),
    )

    result = agent.identify(incident())

    assert result["status"] == "targets_identified"
    assert repository.calls[1][0:2] == ("stream_crossings", 9001)
    assert not any(call[0] == "roads_near_station" for call in repository.calls)
    site = result["response_sites"][0]
    assert site["stream"]["water_source_id"] == 9001
    assert site["allocation_location"] != site["crossing_location"]
    assert site["allocation_eligible"] is True


def test_station_fallback_searches_30m_then_expands_to_signal_precision():
    road = candidate("secondary", distance=75)
    repository = FakeRepository(nearby_by_radius={100.0: [road]})
    agent = FloodRoadTargetAgent(
        repository=repository,
        mapbox_client=FakeMapbox(),
        primary_station_radius_m=30,
        maximum_station_radius_m=250,
    )

    result = agent.identify(incident(precision=100))

    radii = [call[2] for call in repository.calls if call[0] == "roads_near_station"]
    assert radii == [30.0, 100.0]
    assert result["response_sites"][0]["strategy"] == "station_buffer_expanded"
    assert result["response_sites"][0]["local_match_confidence"] == "low"


def test_stream_identity_without_line_geometry_uses_station_fallback():
    road = candidate("secondary", distance=12)
    repository = FakeRepository(
        stream={"stream_id": 1, "water_source_id": 2, "has_geometry": False},
        nearby_by_radius={30.0: [road]},
    )
    result = FloodRoadTargetAgent(
        repository=repository,
        mapbox_client=FakeMapbox(),
    ).identify(incident())

    assert result["response_sites"][0]["strategy"] == "station_buffer_primary"
    assert not any(call[0] == "stream_crossings" for call in repository.calls)


def test_distinct_nearby_roads_are_not_clustered():
    repository = FakeRepository(
        stream={"stream_id": 1, "water_source_id": 2, "has_geometry": True},
        crossings=[
            candidate("primary", feature_id="way/a", road_ref="1"),
            candidate(
                "secondary",
                feature_id="way/b",
                road_ref="2",
                latitude=32.0002,
            ),
        ],
    )
    result = FloodRoadTargetAgent(
        repository=repository,
        mapbox_client=FakeMapbox(),
    ).identify(incident())

    assert len(result["response_sites"]) == 2


def test_duplicate_carriageway_points_for_same_road_are_collapsed():
    repository = FakeRepository(
        stream={"stream_id": 1, "water_source_id": 2, "has_geometry": True},
        crossings=[
            candidate("motorway", feature_id="way/a", road_ref="1"),
            candidate(
                "motorway",
                feature_id="way/b",
                road_ref="1",
                latitude=32.0002,
            ),
        ],
    )
    result = FloodRoadTargetAgent(
        repository=repository,
        mapbox_client=FakeMapbox(),
    ).identify(incident())

    assert len(result["response_sites"]) == 1


def test_mapbox_failure_retains_site_but_prevents_automatic_allocation():
    repository = FakeRepository(
        stream={"stream_id": 1, "water_source_id": 2, "has_geometry": True},
        crossings=[candidate("primary")],
    )
    result = FloodRoadTargetAgent(
        repository=repository,
        mapbox_client=FakeMapbox(fail=True),
    ).identify(incident())

    assert result["status"] == "verification_incomplete"
    assert len(result["response_sites"]) == 1
    assert result["response_sites"][0]["allocation_eligible"] is False
    assert result["allocation_ready_sites"] == []


def test_no_candidates_returns_stream_access_advisory():
    repository = FakeRepository(
        stream={"stream_id": 1, "water_source_id": 2, "has_geometry": True},
        crossings=[],
    )
    result = FloodRoadTargetAgent(
        repository=repository,
        mapbox_client=FakeMapbox(),
    ).identify(incident())

    assert result["status"] == "no_road_targets"
    assert result["resource_allocations"] == []
    assert result["advisories"][0]["action"] == "warn_and_restrict_stream_access"

