import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from ecoguard.resource_allocator.allocation_agent import ResourceAllocationAgent


NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


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
            }

            for candidate in candidates:
                if len(active) >= required_count:
                    break
                station_id = candidate["database_id"]
                resource_key = (recommended_unit, station_id)
                if resource_key in occupied:
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
                }
                self._next_id += 1
                self._rows.append(row)
                active.append(row)
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


def station(
    database_id,
    name,
    latitude,
    longitude,
    precision=None,
    district="test-district",
    station_id=None,
):
    properties = {
        "database_id": database_id,
        "station_id": station_id or database_id,
        "name": name,
        "district": district,
    }
    if precision is not None:
        properties["precision"] = precision
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
        "response_actions": [{"timeframe": "immediate"}],
    }


def allocation_request(incident_id, plan):
    return {
        "incident_id": incident_id,
        "queued_at": NOW,
        "response_plan": plan,
    }


@pytest.mark.parametrize("latitude", [float("nan"), float("inf"), 91, True])
def test_invalid_coordinates_are_rejected(latitude):
    with pytest.raises(ValueError):
        ResourceAllocationAgent._coordinates(
            {"latitude": latitude, "longitude": 35}
        )


def test_coordinator_incident_id_owns_allocation_and_release():
    fire_reader = Mock(
        return_value=catalog(station(1, "Fire station", 31.01, 35.0))
    )
    allocation_repository = InMemoryAllocationRepository()
    agent = ResourceAllocationAgent(
        station_readers={"fire_department": fire_reader},
        allocation_repository=allocation_repository,
    )
    catalog_station = agent._station_catalogs["fire_department"][0]

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
    agent = ResourceAllocationAgent(
        station_readers=readers,
        allocation_repository=InMemoryAllocationRepository(),
    )
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


def test_higher_operational_risk_gets_contended_stations_first():
    fire_reader = Mock(
        return_value=catalog(
            *[
                station(number, f"Station {number}", 31 + number / 1000, 35)
                for number in range(1, 5)
            ]
        )
    )
    agent = ResourceAllocationAgent(
        station_readers={"fire_department": fire_reader},
        allocation_repository=InMemoryAllocationRepository(),
    )
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
        "requested": 4,
        "assigned": 4,
        "shortfall": 0,
    }
    assert results[1]["requirements"]["fire_department"] == {
        "requested": 2,
        "assigned": 0,
        "shortfall": 2,
    }
    assert results[1]["status"] == "partial"
    assert fire_reader.call_count == 1


def test_concurrent_batches_cannot_claim_the_same_station():
    station_catalog = catalog(station(1, "Only station", 31.01, 35.0))
    allocation_repository = InMemoryAllocationRepository()
    agents = [
        ResourceAllocationAgent(
            station_readers={"fire_department": lambda: station_catalog},
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
    assert ResourceAllocationAgent._resource_key(
        recommended_unit,
        {"database_id": 42},
    ) == (recommended_unit, 42)


def test_unknown_resource_type_has_no_implicit_identity_rule():
    with pytest.raises(ValueError, match="unsupported resource type"):
        ResourceAllocationAgent._resource_key(
            "unknown_resource",
            {"database_id": 42},
        )


@pytest.mark.parametrize("planning_status", ["failed", "skipped"])
def test_unsuccessful_planner_status_is_preserved(planning_status):
    fire_reader = Mock(return_value=catalog())
    agent = ResourceAllocationAgent(
        station_readers={"fire_department": fire_reader},
        allocation_repository=InMemoryAllocationRepository(),
    )
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
