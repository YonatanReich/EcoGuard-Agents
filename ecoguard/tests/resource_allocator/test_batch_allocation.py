from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from ecoguard.resource_allocator.allocation_agent import ResourceAllocationAgent


NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


def station(
    station_id,
    name,
    latitude,
    longitude,
    precision=None,
    district="test-district",
):
    properties = {
        "station_id": station_id,
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
        return_value=catalog(station("fire-1", "Fire station", 31.01, 35.0))
    )
    agent = ResourceAllocationAgent(
        station_readers={"fire_department": fire_reader},
    )
    catalog_station = agent._station_catalogs["fire_department"][0]

    assert fire_reader.call_count == 1
    assert catalog_station["resource_key"] == (
        "fire_department",
        "test-district",
        "Fire station",
    )
    assert catalog_station["assigned_incident_id"] is None

    result = agent.allocate_batch(
        [allocation_request("incident-123", response_plan("planner-event-456"))],
        now=NOW,
    )[0]

    assert result["incident_id"] == "incident-123"
    assert result["event_id"] == "planner-event-456"
    assert result["allocated_units"]["fire_stations"][0][
        "assigned_incident_id"
    ] == "incident-123"
    assert catalog_station["assigned_incident_id"] == "incident-123"
    assert len(agent.release_incident("incident-123")) == 1
    assert catalog_station["assigned_incident_id"] is None
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
                station("fire-1", "Coarse fire station", 31.03, 35.0, "city"),
                {
                    "type": "Feature",
                    "geometry": None,
                    "properties": {"station_id": "fire-2", "name": "Unlocated"},
                },
            )
        ),
        "police": Mock(
            return_value=catalog(
                station("police-1", "Police station", 31.02, 35.0)
            )
        ),
        "medical_services": Mock(
            return_value=catalog(
                station("mda-1", "MDA station", 31.01, 35.0, "street")
            )
        ),
    }
    agent = ResourceAllocationAgent(station_readers=readers)
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
                station(f"fire-{number}", f"Station {number}", 31 + number / 1000, 35)
                for number in range(1, 5)
            ]
        )
    )
    agent = ResourceAllocationAgent(
        station_readers={"fire_department": fire_reader}
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
    station_catalog = catalog(station("fire-1", "Only station", 31.01, 35.0))
    agent = ResourceAllocationAgent(
        station_readers={"fire_department": lambda: station_catalog}
    )
    requests = [
        allocation_request("incident-a", response_plan("event-a")),
        allocation_request("incident-b", response_plan("event-b")),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda request: agent.allocate_batch([request], now=NOW)[0],
                requests,
            )
        )

    assigned = [
        result["requirements"]["fire_department"]["assigned"]
        for result in results
    ]
    assert sum(assigned) == 1
    assert len(agent.active_allocations()) == 1


@pytest.mark.parametrize("planning_status", ["failed", "skipped"])
def test_unsuccessful_planner_status_is_preserved(planning_status):
    fire_reader = Mock(return_value=catalog())
    agent = ResourceAllocationAgent(
        station_readers={"fire_department": fire_reader}
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
