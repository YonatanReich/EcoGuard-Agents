import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ecoguard.analyzers.flood.risk_analysis_schemas import (
    FloodRiskAssessment,
)
from ecoguard.shared.schemas import risk_level_for_score
from ecoguard.resource_allocator.allocation_agent import ResourceAllocationAgent
from ecoguard.resource_allocator.allocation_agent import (
    EARTHQUAKE_MINIMUM_RESPONSE_POLICY,
)
from ecoguard.resource_allocator.geo import coordinates
from ecoguard.resource_allocator.station_catalog import resource_key
from ecoguard.resource_allocator.mapbox_client import RoutingError


NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


class FakeRoutingClient:
    provider = "mapbox"
    profile = "mapbox/driving-traffic"
    matrix_max_sources = 9

    def __init__(
        self,
        durations_by_name=None,
        snap_distance_m=0,
        unreachable_names=None,
    ):
        self.durations_by_name = durations_by_name or {}
        self.snap_distance_m = snap_distance_m
        self.unreachable_names = set(unreachable_names or [])
        self.metric_calls = []
        self.route_calls = []

    def _road_access(self, event_location):
        return {
            "input_location": event_location.copy(),
            "snapped_location": event_location.copy(),
            "snap_distance_m": self.snap_distance_m,
            "road_name": "Test road",
        }

    def _duration(self, station):
        return self.durations_by_name.get(
            station["name"],
            60 + abs(station["latitude"] - 31) * 10000,
        )

    def travel_metrics(self, stations, event_location):
        self.metric_calls.append([station["name"] for station in stations])
        return {
            "metrics": [
                None
                if station["name"] in self.unreachable_names
                else {
                    "duration_s": self._duration(station),
                    "distance_m": self._duration(station) * 10,
                    "origin_snapped_location": {
                        "latitude": station["latitude"],
                        "longitude": station["longitude"],
                    },
                    "origin_snap_distance_m": 0,
                }
                for station in stations
            ],
            "road_access": self._road_access(event_location),
        }

    def route(self, station, event_location):
        self.route_calls.append(station["resource_key"])
        duration = self._duration(station)
        road_access = self._road_access(event_location)
        destination = road_access["snapped_location"]
        offroad = self.snap_distance_m > 100
        return {
            "status": "partial_offroad" if offroad else "complete",
            "provider": self.provider,
            "profile": self.profile,
            "distance_m": duration * 10,
            "duration_s": duration,
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [station["longitude"], station["latitude"]],
                    [destination["longitude"], destination["latitude"]],
                ],
            },
            "origin": None,
            "destination": road_access,
            "road_access_verified": not offroad,
            "requires_field_access_confirmation": offroad,
            "offroad_segment": None,
            "steps_he": [],
        }


class FailingRoutingClient(FakeRoutingClient):
    def travel_metrics(self, stations, event_location):
        raise RoutingError("Mapbox is unavailable")


class InMemoryAllocationRepository:
    """Test double with the same atomic claim semantics as PostgreSQL."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rows = []
        self._next_id = 1

    def claim_stations(
        self,
        *,
        incident_id,
        recommended_unit,
        candidates,
        required_count,
        risk_score,
        risk_level,
        allocated_at,
        allocation_policy=None,
        allocation_basis=None,
        quantity_source=None,
    ):
        with self._lock:
            active = [
                row
                for row in self._rows
                if row["incident_id"] == incident_id
                and row["recommended_unit"] == recommended_unit
                and row["released_at"] is None
            ]
            occupied = {
                (row["recommended_unit"], row["station_id"])
                for row in self._rows
                if row["released_at"] is None
                and row["recommended_unit"] != "police"
            }
            active_station_ids = {row["station_id"] for row in active}

            for candidate in candidates:
                if len(active) >= required_count:
                    break
                station_id = candidate["database_id"]
                resource_key = (recommended_unit, station_id)
                if (
                    station_id in active_station_ids
                    or resource_key in occupied
                ):
                    continue

                row = {
                    "id": self._next_id,
                    "incident_id": incident_id,
                    "recommended_unit": recommended_unit,
                    "station_id": station_id,
                    "allocated_at": allocated_at,
                    "released_at": None,
                    "release_reason": None,
                    "distance_km": candidate["distance_km"],
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "allocation_policy": allocation_policy,
                    "allocation_basis": allocation_basis,
                    "quantity_source": quantity_source,
                }
                self._next_id += 1
                self._rows.append(row)
                active.append(row)
                active_station_ids.add(station_id)
                occupied.add(resource_key)

            return [row.copy() for row in active]

    def release_incident(self, incident_id, *, released_at, reason):
        with self._lock:
            released = []
            for row in self._rows:
                if (
                    row["incident_id"] != incident_id
                    or row["released_at"] is not None
                ):
                    continue
                row["released_at"] = released_at
                row["release_reason"] = reason
                released.append(row.copy())
            return released

    def active_allocations(self):
        with self._lock:
            return [
                row.copy() for row in self._rows if row["released_at"] is None
            ]


def allocation_agent(
    station_readers,
    routing_client=None,
    allocation_repository=None,
    police_responsibility_reader=None,
    town_reader=None,
    flood_target_agent=None,
    incident_reader=None,
):
    return ResourceAllocationAgent(
        station_readers=station_readers,
        routing_client=routing_client or FakeRoutingClient(),
        allocation_repository=(
            allocation_repository or InMemoryAllocationRepository()
        ),
        police_responsibility_reader=(
            police_responsibility_reader or (lambda **_: None)
        ),
        town_reader=town_reader or (lambda **_: None),
        flood_target_agent=flood_target_agent or Mock(),
        incident_reader=incident_reader or (lambda _: None),
    )


def station(
    database_id,
    name,
    latitude,
    longitude,
    precision=None,
    district="test-district",
    station_id=None,
    kind=None,
):
    properties = {
        "database_id": database_id,
        "station_id": station_id or database_id,
        "name": name,
        "district": district,
    }
    if precision is not None:
        properties["precision"] = precision
    if kind is not None:
        properties["kind"] = kind
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [longitude, latitude],
        },
        "properties": properties,
    }


def catalog(*features):
    return {
        "type": "FeatureCollection",
        "features": list(features),
        "located": len(features),
        "total": len(features),
    }


def response_plan(
    event_id,
    *,
    risk_score=50,
    risk_level="low",
    units=None,
    planning_status="success",
):
    return {
        "metadata": {
            "planning_status": planning_status,
            "timestamp": NOW.isoformat(),
        },
        "event_id": event_id,
        "location": {"latitude": 31.0, "longitude": 35.0},
        "responding_to": {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "risk_semantics": "detected_event_operational_risk",
        },
        "recommended_units": units or ["fire_department"],
        "response_actions": [
            {
                "action": "Carry out the assigned operational response.",
                "responsible_unit": unit,
                "timeframe": "immediate",
            }
            for unit in (units or ["fire_department"])
        ],
    }


def allocation_request(incident_id, plan):
    return {
        "incident_id": incident_id,
        "queued_at": NOW,
        "response_plan": plan,
    }


def earthquake_allocation_request(incident_id, *, units, risk_score=60):
    plan = response_plan(incident_id, units=units)
    plan["hazard_type"] = "earthquake"
    # This was None until earthquake gained a score on the shared scale. The
    # policy still fixes how many stations go -- one per unit type -- but the
    # queue position now comes from the same 0-100 number Fire and Flood
    # carry, so a large earthquake no longer sorts behind every brush fire.
    plan["responding_to"] = {
        "risk_semantics": "detected_event_operational_risk",
        "risk_score": risk_score,
        "risk_level": risk_level_for_score(risk_score),
    }
    return {
        **allocation_request(incident_id, plan),
        "allocation_policy": EARTHQUAKE_MINIMUM_RESPONSE_POLICY,
    }


@pytest.mark.parametrize("latitude", [float("nan"), float("inf"), 91, True])
def test_invalid_coordinates_are_rejected(latitude):
    with pytest.raises(ValueError):
        coordinates({"latitude": latitude, "longitude": 35})


def test_coordinator_incident_id_owns_allocation_and_release():
    fire_reader = Mock(
        return_value=catalog(station(1, "Fire station", 31.01, 35.0))
    )
    allocation_repository = InMemoryAllocationRepository()
    agent = allocation_agent(
        {"fire_department": fire_reader},
        allocation_repository=allocation_repository,
    )
    catalog_station = agent.station_catalog.catalogs["fire_department"][0]

    assert fire_reader.call_count == 1
    assert catalog_station["resource_key"] == ("fire_department", 1)
    assert "assigned_incident_id" not in catalog_station

    result = agent.allocate_batch(
        [allocation_request("incident-123", response_plan("planner-event-456"))],
        now=NOW,
    )[0]

    assert result["incident_id"] == "incident-123"
    assert result["event_id"] == "planner-event-456"
    assert result["allocated_units"]["fire_stations"][0][
        "assigned_incident_id"
    ] == "incident-123"
    assert list(agent.active_allocations()) == ["incident-123"]
    assert len(agent.release_incident("incident-123")) == 1
    assert agent.active_allocations() == {}
    assert agent.release_incident("incident-123") == []

    agent.allocate_batch(
        [allocation_request("incident-789", response_plan("planner-event-789"))],
        now=NOW,
    )
    assert fire_reader.call_count == 1


def test_allocator_attaches_only_frontend_settlement_fields():
    town_reader = Mock(return_value={
        "town_id": "test-town",
        "name_he": "עיר בדיקה",
        "population": 12_000,
        "households": 4_200,
        "authority": "רשות בדיקה",
        "authority_type": "עירייה",
        "authority_phone": "03-0000000",
        "authority_address": "רחוב בדיקה 1",
        "authority_website": "https://example.test",
        "area_km2": 8.5,
        "police_station": "must not be exposed",
    })
    agent = allocation_agent(
        {
            "fire_department": lambda: catalog(
                station(1, "Fire station", 31.01, 35.0)
            )
        },
        town_reader=town_reader,
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1"))],
        now=NOW,
    )[0]

    assert result["settlement"] == {
        "population": 12_000,
        "households": 4_200,
        "authority": "רשות בדיקה",
        "authority_type": "עירייה",
        "authority_phone": "03-0000000",
        "authority_address": "רחוב בדיקה 1",
        "authority_website": "https://example.test",
        "area_km2": 8.5,
    }
    town_reader.assert_called_once_with(latitude=31.0, longitude=35.0)


def _flood_site(severity, road_class="primary", target_id="target-primary"):
    return {
        "target_id": target_id,
        "severity_level": severity,
        "urban": True,
        "road": {"base_class": road_class, "ref": "4"},
        "mapbox_verification": {"mapbox_snap_distance_m": 4.0},
        "allocation_location": {"latitude": 32.0, "longitude": 34.8},
        "allocation_eligible": True,
    }


def _flood_risk(severity, incident_id="INC-FLOOD-1"):
    scores = {
        3: (40, "medium"),
        4: (60, "high"),
        5: (80, "critical"),
        6: (100, "critical"),
    }
    score, level = scores[severity]
    return FloodRiskAssessment(
        metadata={"timestamp": NOW, "analysis_status": "success"},
        event_id=incident_id,
        risk_score=score,
        risk_level=level,
        confidence="high",
        hydrologic_severity_level=severity,
        return_period_years={3: 10, 4: 20, 5: 50, 6: 100}[severity],
        alert_level={
            3: "active",
            4: "severe",
            5: "emergency",
            6: "emergency",
        }[severity],
        change_type="initial",
        primary_drivers=[f"Severity {severity} was observed"],
        explanation="Detected Flood operational risk derived from current hydrometric severity.",
    )


@pytest.mark.parametrize(
    ("severity", "risk_score", "risk_level"),
    [
        (3, 40.0, "medium"),
        (4, 60.0, "high"),
        (5, 80.0, "critical"),
        (6, 100.0, "critical"),
    ],
)
def test_flood_uses_shared_0_to_100_risk_scale(
    severity, risk_score, risk_level
):
    agent = allocation_agent({})
    prepared = agent.request_preparer.prepare(
        {
            "incident_id": "INC-FLOOD-1",
            "hazard": "flood",
            "queued_at": NOW,
            "risk_assessment": _flood_risk(severity),
            "flood_targeting": {
                "allocation_ready_sites": [_flood_site(severity)],
            },
        },
        NOW,
    )

    assert prepared["response_plan"]["recommended_units"] == ["police"]
    assert "station_requirements" not in prepared["response_plan"]
    assert prepared["risk_score"] == risk_score
    assert prepared["risk_level"] == risk_level
    assert prepared["hazard"] == "flood"


def test_fire_and_flood_receive_the_same_level_for_the_same_score():
    agent = allocation_agent({})
    fire = agent.request_preparer.prepare(
        allocation_request(
            "INC-FIRE-1",
            response_plan("fire-event", risk_score=60, risk_level="high"),
        ),
        NOW,
    )
    flood = agent.request_preparer.prepare(
        {
            "incident_id": "INC-FLOOD-1",
            "hazard": "flood",
            "queued_at": NOW,
            "risk_assessment": _flood_risk(4),
            "flood_targeting": {
                "allocation_ready_sites": [_flood_site(4)],
            },
        },
        NOW,
    )

    assert fire["risk_score"] == flood["risk_score"] == 60.0
    assert fire["risk_level"] == flood["risk_level"] == "high"


def test_flood_allocator_rejects_targeting_that_disagrees_with_risk_analyzer():
    agent = allocation_agent({})

    with pytest.raises(
        ValueError,
        match="risk severity does not match targeting evidence",
    ):
        agent.request_preparer.prepare(
            {
                "incident_id": "INC-FLOOD-1",
                "hazard": "flood",
                "queued_at": NOW,
                "risk_assessment": _flood_risk(3),
                "flood_targeting": {
                    "allocation_ready_sites": [_flood_site(4)],
                },
            },
            NOW,
        )


def test_flood_allocator_requires_risk_analyzer_output():
    agent = allocation_agent({})

    with pytest.raises(ValueError, match="flood_risk_assessment is required"):
        agent.request_preparer.prepare(
            {
                "incident_id": "INC-FLOOD-1",
                "hazard": "flood",
                "queued_at": NOW,
                "flood_targeting": {
                    "allocation_ready_sites": [_flood_site(4)],
                },
            },
            NOW,
        )


def test_flood_allocator_selects_the_highest_priority_verified_road():
    agent = allocation_agent({})
    street = _flood_site(4, "street", "street-target")
    motorway = _flood_site(4, "motorway", "motorway-target")

    prepared = agent.request_preparer.prepare(
        {
            "incident_id": "INC-FLOOD-1",
            "hazard": "flood",
            "queued_at": NOW,
            "risk_assessment": _flood_risk(4),
            "flood_targeting": {
                "allocation_ready_sites": [street, motorway],
            },
        },
        NOW,
    )

    assert prepared["allocation_target"]["target_id"] == "motorway-target"
    assert prepared["allocation_target"]["covered_response_site_ids"] == [
        "street-target",
        "motorway-target",
    ]


def test_flood_allocator_assigns_police_to_gauge_when_no_site_was_verified():
    agent = allocation_agent({})

    prepared = agent.request_preparer.prepare(
        {
            "incident_id": "INC-FLOOD-1",
            "hazard": "flood",
            "queued_at": NOW,
            "risk_assessment": _flood_risk(4),
            "flood_targeting": {
                "allocation_ready_sites": [],
                "hydrometric_sources": [{
                    "station": {
                        "id": 50,
                        "latitude": 30.735,
                        "longitude": 35.235,
                        "severity_level": 4,
                    },
                    "strategy": "station_buffer_primary",
                    "stream": None,
                }],
            },
        },
        NOW,
    )

    assert prepared["response_plan"]["recommended_units"] == ["police"]
    assert prepared["response_plan"]["location"] == {
        "latitude": 30.735,
        "longitude": 35.235,
    }
    assert prepared["allocation_target"]["target_type"] == (
        "hydrometric_station_fallback"
    )
    assert prepared["allocation_target"]["requires_road_access_resolution"] is True


def test_resource_allocator_discovers_flood_roads_and_assigns_one_police_station():
    targeting = {
        "incident_id": "INC-FLOOD-1",
        "status": "targets_identified",
        "response_sites": [_flood_site(3)],
        "allocation_ready_sites": [_flood_site(3)],
        "resource_allocations": [],
        "advisories": [],
    }
    flood_target_agent = Mock()
    flood_target_agent.identify.return_value = targeting
    agent = allocation_agent(
        {
            "fire_department": lambda: catalog(
                station(1, "Fire station", 32.01, 34.8)
            ),
            "police": lambda: catalog(
                station(2, "Police station", 32.02, 34.8, kind="station")
            ),
        },
        flood_target_agent=flood_target_agent,
        incident_reader=lambda incident_id: (
            incident if incident_id == "INC-FLOOD-1" else None
        ),
    )
    incident = {"id": "INC-FLOOD-1", "signals": []}
    result = SimpleNamespace(
        incident_id="INC-FLOOD-1",
        hazard="flood",
        route="emergency",
        requested_at=NOW,
        planner_result=None,
        risk_assessment=_flood_risk(3),
        resource_allocation_result=None,
    )

    allocations = agent.allocate_processing_results([result])

    flood_target_agent.identify.assert_called_once_with(incident)
    station_allocation = result.resource_allocation_result["station_allocation"]
    assert station_allocation["requirements"]["police"] == {
        "requested": 1,
        "assigned": 1,
        "shortfall": 0,
    }
    assert len(station_allocation["allocated_units"]["police_stations"]) == 1
    assert allocations["INC-FLOOD-1"] is station_allocation


def test_flood_deescalation_preserves_existing_allocation_without_retargeting():
    flood_target_agent = Mock()
    agent = allocation_agent(
        {
            "police": lambda: catalog(
                station(2, "Police station", 32.02, 34.8, kind="station")
            ),
        },
        flood_target_agent=flood_target_agent,
        incident_reader=lambda _: pytest.fail(
            "preserved allocation must not reload incident"
        ),
    )
    result = SimpleNamespace(
        incident_id="INC-FLOOD-1",
        hazard="flood",
        route="emergency",
        requested_at=NOW,
        planner_result=None,
        resource_allocation_result=None,
        requires_resource_allocation=False,
        preserve_existing_response=True,
    )

    assert agent.allocate_processing_results([result]) == {}
    assert result.resource_allocation_result is None
    flood_target_agent.identify.assert_not_called()


def test_flood_without_road_crossing_assigns_police_and_routes_to_road_access():
    targeting = {
        "incident_id": "INC-FLOOD-NO-ROAD",
        "status": "no_road_targets",
        "response_sites": [],
        "allocation_ready_sites": [],
        "hydrometric_sources": [{
            "station": {
                "id": 70,
                "latitude": 30.735,
                "longitude": 35.235,
                "severity_level": 4,
            },
            "strategy": "station_buffer_primary",
            "stream": None,
        }],
        "resource_allocations": [],
        "advisories": [],
    }
    flood_target_agent = Mock()
    flood_target_agent.identify.return_value = targeting
    routing_client = FakeRoutingClient(snap_distance_m=175)
    incident = {"id": "INC-FLOOD-NO-ROAD", "signals": []}
    agent = allocation_agent(
        {
            "police": lambda: catalog(
                station(2, "Police station", 30.75, 35.22, kind="station")
            ),
        },
        routing_client=routing_client,
        flood_target_agent=flood_target_agent,
        incident_reader=lambda incident_id: (
            incident if incident_id == incident["id"] else None
        ),
    )
    result = SimpleNamespace(
        incident_id=incident["id"],
        hazard="flood",
        route="emergency",
        requested_at=NOW,
        planner_result=None,
        risk_assessment=_flood_risk(4, incident["id"]),
        resource_allocation_result=None,
    )

    agent.allocate_processing_results([result])

    allocation = result.resource_allocation_result["station_allocation"]
    assigned = allocation["allocated_units"]["police_stations"]
    assert allocation["requirements"]["police"] == {
        "requested": 1,
        "assigned": 1,
        "shortfall": 0,
    }
    assert len(assigned) == 1
    assert assigned[0]["route"]["status"] == "partial_offroad"
    assert assigned[0]["route"]["duration_s"] is not None
    assert assigned[0]["route"]["requires_field_access_confirmation"] is True
    assert assigned[0]["route"]["offroad_segment"]["access_verified"] is False
    assert assigned[0]["route"]["offroad_segment"]["distance_m"] == 175
    assert result.resource_allocation_result["allocation_target"]["target_type"] == (
        "hydrometric_station_fallback"
    )


def test_allocator_returns_no_settlement_outside_every_town_polygon():
    agent = allocation_agent(
        {
            "fire_department": lambda: catalog(
                station(1, "Fire station", 31.01, 35.0)
            )
        },
        town_reader=lambda **_: None,
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1"))],
        now=NOW,
    )[0]

    assert result["settlement"] is None


def test_batch_uses_fire_police_and_mda_db_catalogs_including_coarse_points():
    readers = {
        "fire_department": Mock(
            return_value=catalog(
                station(1, "Coarse fire station", 31.03, 35.0, "city"),
                {
                    "type": "Feature",
                    "geometry": None,
                    "properties": {"database_id": 2, "name": "Unlocated"},
                },
            )
        ),
        "police": Mock(
            return_value=catalog(
                station(1, "Police station", 31.02, 35.0)
            )
        ),
        "medical_services": Mock(
            return_value=catalog(
                station(1, "MDA station", 31.01, 35.0, "street")
            )
        ),
    }
    agent = allocation_agent(readers)
    plan = response_plan(
        "event-1",
        units=["fire_department", "police", "medical_services"],
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", plan)], now=NOW
    )[0]

    assert set(result["allocated_units"]) == {
        "fire_stations",
        "police_stations",
        "mda_stations",
    }
    assert result["allocated_units"]["fire_stations"][0]["precision"] == "city"
    assert len(result["allocated_units"]["fire_stations"]) == 1
    assert (
        result["allocated_units"]["mda_stations"][0]["unit_type"]
        == "mda_station"
    )
    assert result["status"] == "fulfilled"
    assert all(reader.call_count == 1 for reader in readers.values())


def test_earthquake_policy_requests_one_station_per_supported_unit_type():
    readers = {
        "fire_department": Mock(return_value=catalog(
            station(1, "Fire one", 31.01, 35.0),
            station(2, "Fire two", 31.02, 35.0),
        )),
        "police": Mock(return_value=catalog(
            station(3, "Police", 31.03, 35.0),
        )),
        "medical_services": Mock(return_value=catalog(
            station(4, "MDA", 31.04, 35.0),
        )),
    }
    agent = allocation_agent(readers)
    result = agent.allocate_batch([
        earthquake_allocation_request(
            "INC-EQ-1",
            units=[
                "fire_department",
                "police",
                "medical_services",
                "home_front_command",
            ],
        )
    ], now=NOW)[0]

    assert result["hazard"] == "earthquake"
    assert result["allocation_policy"] == "earthquake_minimum_response_v1"
    assert result["allocation_basis"] == "protocol_recommended_units"
    assert result["quantity_source"] == "ecoguard_minimum_response_policy"
    # These asserted None while earthquake carried no operational risk. The
    # policy governs the quantity -- one station per unit type, below -- and
    # no longer governs the queue position, which is now the shared score.
    assert result["risk_score"] == 60.0
    assert result["risk_level"] == "high"
    assert all(
        requirement["requested"] == 1
        for requirement in result["requirements"].values()
    )
    assert len(result["allocated_units"]["fire_stations"]) == 1
    assert len(result["allocated_units"]["police_stations"]) == 1
    assert len(result["allocated_units"]["mda_stations"]) == 1
    assert result["unsupported_units"] == ["home_front_command"]
    fire_station = result["allocated_units"]["fire_stations"][0]
    assert fire_station["risk_score"] == 60.0
    assert fire_station["risk_level"] == "high"
    assert fire_station["route"]["geometry"]["type"] == "LineString"
    assert fire_station["route"]["estimated_arrival_at"] is not None


def test_team_quantity_does_not_change_the_number_of_allocated_stations():
    agent = allocation_agent({
        "fire_department": lambda: catalog(
            station(1, "Fire one", 31.01, 35.0),
            station(2, "Fire two", 31.02, 35.0),
            station(3, "Fire three", 31.03, 35.0),
        ),
    })
    plan = response_plan("event-1")
    plan["teams_required"] = 3

    result = agent.allocate_batch(
        [allocation_request("incident-1", plan)],
        now=NOW,
    )[0]

    assert result["requirements"]["fire_department"] == {
        "requested": 1,
        "assigned": 1,
        "shortfall": 0,
    }
    assert len(result["allocated_units"]["fire_stations"]) == 1


def test_allocator_attaches_successful_earthquake_allocation_directly():
    agent = allocation_agent({
        "fire_department": lambda: catalog(
            station(1, "Fire station", 31.01, 35.0)
        ),
    })
    request = earthquake_allocation_request(
        "INC-EQ-1",
        units=["fire_department"],
    )
    result = SimpleNamespace(
        incident_id="INC-EQ-1",
        hazard="earthquake",
        route="emergency",
        requested_at=NOW,
        planner_result=request["response_plan"],
        resource_allocation_result=None,
    )

    allocations = agent.allocate_processing_results([result])

    allocation = allocations["INC-EQ-1"]
    assert result.resource_allocation_result is allocation
    assert allocation["allocation_policy"] == EARTHQUAKE_MINIMUM_RESPONSE_POLICY
    assert len(allocation["allocated_units"]["fire_stations"]) == 1
    assert "station_allocation" not in allocation


def test_earthquake_policy_does_not_create_eta_when_routing_is_unavailable():
    agent = allocation_agent(
        {"fire_department": lambda: catalog(
            station(1, "Fire", 31.01, 35.0),
        )},
        routing_client=FailingRoutingClient(),
    )
    result = agent.allocate_batch([
        earthquake_allocation_request("INC-EQ-1", units=["fire_department"])
    ], now=NOW)[0]

    assigned = result["allocated_units"]["fire_stations"][0]
    assert assigned["selection_reason"] == "straight_line_fallback"
    assert assigned["route"]["estimated_arrival_at"] is None
    assert result["routing_status"] == "unavailable"


def test_higher_operational_risk_gets_contended_stations_first():
    fire_reader = Mock(
        return_value=catalog(
            *[
                station(number, f"Station {number}", 31 + number / 1000, 35)
                for number in range(1, 5)
            ]
        )
    )
    agent = allocation_agent({"fire_department": fire_reader})
    requests = [
        allocation_request(
            "medium-incident",
            response_plan("medium-event", risk_score=60, risk_level="medium"),
        ),
        allocation_request(
            "critical-incident",
            response_plan("critical-event", risk_score=95, risk_level="critical"),
        ),
    ]

    results = agent.allocate_batch(requests, now=NOW)

    assert [result["incident_id"] for result in results] == [
        "critical-incident",
        "medium-incident",
    ]
    assert results[0]["requirements"]["fire_department"] == {
        "requested": 1,
        "assigned": 1,
        "shortfall": 0,
    }
    assert results[1]["requirements"]["fire_department"] == {
        "requested": 1,
        "assigned": 1,
        "shortfall": 0,
    }
    assert results[1]["status"] == "fulfilled"
    assert results[0]["allocated_units"]["fire_stations"][0]["database_id"] == 1
    assert results[1]["allocated_units"]["fire_stations"][0]["database_id"] == 2
    assert fire_reader.call_count == 1


def test_fire_actions_are_preserved_and_attached_to_responsible_stations():
    agent = allocation_agent({
        "fire_department": lambda: catalog(
            station(1, "Fire station", 31.01, 35.0)
        ),
        "police": lambda: catalog(
            station(2, "Police station", 31.02, 35.0)
        ),
    })
    plan = response_plan(
        "fire-event",
        units=["fire_department", "police"],
    )
    plan["response_actions"] = [
        {
            "action": "Contain the fire perimeter.",
            "responsible_unit": "fire_department",
            "timeframe": "ongoing",
        },
        {
            "action": "Establish the initial fire command point.",
            "responsible_unit": "fire_department",
            "timeframe": "within_1_hour",
        },
        {
            "action": "Restrict access to the incident area.",
            "responsible_unit": "police",
            "timeframe": "immediate",
        },
    ]

    result = agent.allocate_batch(
        [allocation_request("fire-incident", plan)], now=NOW
    )[0]

    assert result["response_actions"] == plan["response_actions"]
    assert result["allocated_units"]["fire_stations"][0]["response_actions"] == [
        plan["response_actions"][0],
        plan["response_actions"][1],
    ]
    assert result["allocated_units"]["police_stations"][0]["response_actions"] == [
        plan["response_actions"][2]
    ]


def test_flood_successful_planner_actions_drive_station_allocation():
    agent = allocation_agent({
        "fire_department": lambda: catalog(
            station(1, "Fire station", 31.01, 35.0),
            station(2, "Fire station 2", 31.02, 35.0),
            station(3, "Fire station 3", 31.03, 35.0),
        ),
        "police": lambda: catalog(
            station(4, "Police station", 31.04, 35.0)
        ),
    })
    plan = response_plan(
        "flood-event",
        risk_score=60,
        risk_level="high",
        units=["fire_department", "police"],
    )
    plan["response_actions"] = [
        {
            "action": "Prepare for rescue at the verified road site.",
            "responsible_unit": "fire_department",
            "timeframe": "immediate",
        },
        {
            "action": "Close access to the verified road site.",
            "responsible_unit": "police",
            "timeframe": "immediate",
        },
    ]

    result = agent.allocate_batch([{
        "incident_id": "INC-FLOOD-1",
        "hazard": "flood",
        "queued_at": NOW,
        "risk_assessment": _flood_risk(4),
        "flood_targeting": {
            "allocation_ready_sites": [_flood_site(4)],
        },
        "response_plan": plan,
    }], now=NOW)[0]

    assert result["response_actions"] == plan["response_actions"]
    assert all(
        station_result["response_actions"] == [plan["response_actions"][0]]
        for station_result in result["allocated_units"]["fire_stations"]
    )
    assert len(result["allocated_units"]["fire_stations"]) == 1
    assert result["allocated_units"]["police_stations"][0]["response_actions"] == [
        plan["response_actions"][1]
    ]


def test_concurrent_batches_cannot_claim_the_same_station():
    station_catalog = catalog(station(1, "Only station", 31.01, 35.0))
    allocation_repository = InMemoryAllocationRepository()
    agents = [
        allocation_agent(
            {"fire_department": lambda: station_catalog},
            allocation_repository=allocation_repository,
        )
        for _ in range(2)
    ]
    requests = [
        allocation_request("incident-a", response_plan("event-a")),
        allocation_request("incident-b", response_plan("event-b")),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda pair: pair[0].allocate_batch([pair[1]], now=NOW)[0],
                zip(agents, requests),
            )
        )

    assigned = [
        result["requirements"]["fire_department"]["assigned"]
        for result in results
    ]
    assert sum(assigned) == 1
    assert len(agents[0].active_allocations()) == 1


def test_busy_nearest_station_falls_back_to_next_available_station():
    allocation_repository = InMemoryAllocationRepository()
    agent = ResourceAllocationAgent(
        station_readers={
            "fire_department": lambda: catalog(
                station(1, "Nearest", 31.01, 35.0),
                station(2, "Farther", 31.02, 35.0),
            )
        },
        allocation_repository=allocation_repository,
    )

    first = agent.allocate_batch(
        [allocation_request("incident-a", response_plan("event-a"))],
        now=NOW,
    )[0]
    second = agent.allocate_batch(
        [allocation_request("incident-b", response_plan("event-b"))],
        now=NOW,
    )[0]

    assert first["allocated_units"]["fire_stations"][0]["name"] == "Nearest"
    assert second["allocated_units"]["fire_stations"][0]["name"] == "Farther"


def test_police_allocation_uses_only_the_event_towns_responsible_stations():
    routing = FakeRoutingClient()
    agent = allocation_agent(
        {
            "police": lambda: catalog(
                station(1, "Closer but not responsible", 31.001, 35.0, kind="station"),
                station(2, "Responsible", 31.02, 35.0, kind="station"),
            )
        },
        routing_client=routing,
        police_responsibility_reader=lambda **_: {
            "town_id": "test-town",
            "town_name": "Test town",
            "police_station_ids": [2],
        },
    )

    result = agent.allocate_batch(
        [
            allocation_request(
                "incident-1",
                response_plan(
                    "event-1",
                    risk_score=90,
                    risk_level="critical",
                    units=["police"],
                ),
            )
        ],
        now=NOW,
    )[0]

    assigned = result["allocated_units"]["police_stations"]
    assert [item["database_id"] for item in assigned] == [2]
    assert assigned[0]["selection_reason"] == "responsible_for_area"
    assert assigned[0]["allocation_scope"] == "station"
    assert assigned[0]["severity"] == "critical"
    assert assigned[0]["available_for_ecoguard"] is True
    assert result["severity"] == "critical"
    assert result["allocation_scope"] == "station"
    assert result["requirements"]["police"] == {
        "requested": 1,
        "assigned": 1,
        "shortfall": 0,
    }
    assert routing.metric_calls == [["Responsible"]]


def test_multiple_responsible_police_stations_are_ranked_by_travel_time():
    routing = FakeRoutingClient(
        durations_by_name={"Near but slow": 500, "Far but fast": 100}
    )
    agent = allocation_agent(
        {
            "police": lambda: catalog(
                station(1, "Near but slow", 31.001, 35.0, kind="station"),
                station(2, "Far but fast", 31.02, 35.0, kind="station"),
            )
        },
        routing_client=routing,
        police_responsibility_reader=lambda **_: {
            "town_id": "test-town",
            "town_name": "Test town",
            "police_station_ids": [1, 2],
        },
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1", units=["police"]))],
        now=NOW,
    )[0]

    assigned = result["allocated_units"]["police_stations"][0]
    assert assigned["database_id"] == 2
    assert assigned["selection_reason"] == "nearest_responsible_station"


def test_police_fallback_uses_nearest_full_station_when_town_has_no_mapping():
    agent = allocation_agent(
        {
            "police": lambda: catalog(
                station(1, "Nearby region", 31.001, 35.0, kind="region"),
                station(2, "Nearest full station", 31.01, 35.0, kind="station"),
                station(3, "Far full station", 31.02, 35.0, kind="station"),
            )
        },
        police_responsibility_reader=lambda **_: {
            "town_id": "unmapped-town",
            "town_name": "Unmapped town",
            "police_station_ids": [],
        },
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1", units=["police"]))],
        now=NOW,
    )[0]

    assigned = result["allocated_units"]["police_stations"][0]
    assert assigned["database_id"] == 2
    assert assigned["selection_reason"] == "nearest_police_station_fallback"
    assert result["police_responsibility"]["reason"] == (
        "town_has_no_mapped_police_station"
    )


def test_police_station_can_receive_multiple_incidents_but_retries_are_idempotent():
    repository = InMemoryAllocationRepository()
    agent = allocation_agent(
        {
            "police": lambda: catalog(
                station(1, "Responsible", 31.01, 35.0, kind="station")
            )
        },
        allocation_repository=repository,
        police_responsibility_reader=lambda **_: {
            "town_id": "test-town",
            "town_name": "Test town",
            "police_station_ids": [1],
        },
    )
    first_request = allocation_request(
        "incident-a", response_plan("event-a", units=["police"])
    )
    second_request = allocation_request(
        "incident-b", response_plan("event-b", units=["police"])
    )

    first = agent.allocate_batch([first_request], now=NOW)[0]
    second = agent.allocate_batch([second_request], now=NOW)[0]
    retry = agent.allocate_batch([first_request], now=NOW)[0]

    assert first["requirements"]["police"]["assigned"] == 1
    assert second["requirements"]["police"]["assigned"] == 1
    assert retry["requirements"]["police"]["assigned"] == 1
    assert len(repository.active_allocations()) == 2


def test_repeated_allocation_for_same_incident_is_idempotent():
    agent = ResourceAllocationAgent(
        station_readers={
            "fire_department": lambda: catalog(
                station(1, "Nearest", 31.01, 35.0),
                station(2, "Farther", 31.02, 35.0),
            )
        },
        allocation_repository=InMemoryAllocationRepository(),
    )
    request = allocation_request("incident-a", response_plan("event-a"))

    first = agent.allocate_batch([request], now=NOW)[0]
    second = agent.allocate_batch([request], now=NOW)[0]

    assert first["allocated_units"]["fire_stations"][0]["database_id"] == 1
    assert second["allocated_units"]["fire_stations"][0]["database_id"] == 1
    assert len(agent.active_allocations()["incident-a"]) == 1


@pytest.mark.parametrize(
    "recommended_unit",
    ["fire_department", "police", "medical_services"],
)
def test_every_supported_resource_uses_its_database_id(recommended_unit):
    assert resource_key(
        recommended_unit,
        {"database_id": 42},
    ) == (recommended_unit, 42)


def test_unknown_resource_type_has_no_implicit_identity_rule():
    with pytest.raises(ValueError, match="unsupported resource type"):
        resource_key(
            "unknown_resource",
            {"database_id": 42},
        )


def test_assigned_stations_are_not_sent_to_mapbox_again():
    routing = FakeRoutingClient()
    agent = allocation_agent(
        {
            "fire_department": lambda: catalog(
                station(1, "Near station", 31.001, 35.0),
                station(2, "Far station", 31.02, 35.0),
            )
        },
        routing_client=routing,
    )
    agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1"))],
        now=NOW,
    )
    routing.metric_calls.clear()

    result = agent.allocate_batch(
        [allocation_request("incident-2", response_plan("event-2"))],
        now=NOW,
    )[0]

    assert routing.metric_calls == [["Far station"]]
    assert (
        result["allocated_units"]["fire_stations"][0]["name"]
        == "Far station"
    )


def test_mapbox_search_stops_after_nearby_batch_can_fulfil_request():
    routing = FakeRoutingClient()
    agent = allocation_agent(
        {
            "fire_department": lambda: catalog(
                *[
                    station(
                        number,
                        f"Station {number}",
                        31 + number / 1000,
                        35.0,
                    )
                    for number in range(1, 11)
                ]
            )
        },
        routing_client=routing,
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1"))],
        now=NOW,
    )[0]

    assert len(routing.metric_calls) == 1
    assert len(routing.metric_calls[0]) == 9
    assert "Station 10" not in routing.metric_calls[0]
    assert result["requirements"]["fire_department"]["assigned"] == 1


def test_mapbox_search_expands_when_nearby_batch_has_no_route():
    nearby_names = {f"Station {number}" for number in range(1, 10)}
    routing = FakeRoutingClient(unreachable_names=nearby_names)
    agent = allocation_agent(
        {
            "fire_department": lambda: catalog(
                *[
                    station(
                        number,
                        f"Station {number}",
                        31 + number / 1000,
                        35.0,
                    )
                    for number in range(1, 11)
                ]
            )
        },
        routing_client=routing,
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1"))],
        now=NOW,
    )[0]

    assert [len(batch) for batch in routing.metric_calls] == [9, 1]
    assert result["allocated_units"]["fire_stations"][0]["name"] == "Station 10"


def test_fastest_road_route_wins_over_nearest_straight_line_station():
    routing = FakeRoutingClient(
        durations_by_name={"Near but slow": 600, "Far but fast": 180}
    )
    agent = allocation_agent(
        {
            "fire_department": lambda: catalog(
                station(1, "Near but slow", 31.001, 35.0),
                station(2, "Far but fast", 31.02, 35.0),
            )
        },
        routing_client=routing,
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1"))],
        now=NOW,
    )[0]
    assigned = result["allocated_units"]["fire_stations"][0]

    assert assigned["name"] == "Far but fast"
    assert assigned["selection_reason"] == "shortest_road_travel_time"
    assert assigned["route"]["duration_s"] == 180
    assert assigned["route"]["geometry"]["type"] == "LineString"
    assert assigned["route"]["estimated_arrival_at"] == (
        "2026-09-17T00:03:00+00:00"
    )
    assert len(routing.route_calls) == 1
    assert result["routing_status"] == "complete"


def test_mapbox_failure_falls_back_to_nearest_station_without_fake_eta():
    agent = allocation_agent(
        {
            "fire_department": lambda: catalog(
                station(1, "Near", 31.001, 35.0),
                station(2, "Far", 31.02, 35.0),
            )
        },
        routing_client=FailingRoutingClient(),
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1"))],
        now=NOW,
    )[0]
    assigned = result["allocated_units"]["fire_stations"][0]

    assert assigned["name"] == "Near"
    assert assigned["selection_reason"] == "straight_line_fallback"
    assert assigned["route"]["status"] == "unavailable"
    assert assigned["route"]["duration_s"] is None
    assert result["routing_status"] == "unavailable"
    assert result["status"] == "partial"
    assert result["errors"][0]["reason"] == "road_ranking_unavailable"


def test_offroad_event_is_exposed_as_unverified_last_mile():
    agent = allocation_agent(
        {
            "fire_department": lambda: catalog(
                station(1, "Station", 31.01, 35.0)
            )
        },
        routing_client=FakeRoutingClient(snap_distance_m=500),
    )

    result = agent.allocate_batch(
        [allocation_request("incident-1", response_plan("event-1"))],
        now=NOW,
    )[0]
    route = result["allocated_units"]["fire_stations"][0]["route"]

    assert route["status"] == "partial_offroad"
    assert route["road_access_verified"] is False
    assert route["requires_field_access_confirmation"] is True
    assert result["routing_status"] == "partial_offroad"


@pytest.mark.parametrize("planning_status", ["failed", "skipped"])
def test_unsuccessful_planner_status_is_preserved(planning_status):
    fire_reader = Mock(return_value=catalog())
    agent = allocation_agent({"fire_department": fire_reader})
    plan = response_plan("event-1", planning_status=planning_status)
    plan["metadata"]["reason"] = "planner reason"
    plan["error"] = "planner error" if planning_status == "failed" else None

    result = agent.allocate_batch(
        [allocation_request("incident-1", plan)], now=NOW
    )[0]

    assert result["status"] == planning_status
    assert result["reason"] == f"response_plan_{planning_status}"
    assert result["planner_status"] == planning_status
    assert result["planner_reason"] == "planner reason"
    assert result["planner_error"] == (
        "planner error" if planning_status == "failed" else None
    )
    assert fire_reader.call_count == 1
