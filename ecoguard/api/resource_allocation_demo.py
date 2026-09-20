"""Development-only bridge from a fixed fire plan to the resource allocator."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
from typing import Any

from ecoguard.resource_allocator.allocation_agent import ResourceAllocationAgent
from ecoguard.shared.events import FireSharedEvent


DEMO_INCIDENT_ID = "demo-haifa-fire-allocation"
# The point is intentionally inside the stored Haifa polygon so the frontend
# demo also exercises the strict point-in-polygon settlement lookup.
DEMO_LOCATION = {"latitude": 32.80948, "longitude": 35.059823}


class DemoAllocationRepository:
    """Keep demo claims local so a frontend preview cannot occupy DB stations."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._rows: list[dict[str, Any]] = []
        self._next_id = 1

    def active_allocations(self) -> list[dict[str, Any]]:
        with self._lock:
            return [row.copy() for row in self._rows if row["released_at"] is None]

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
    ) -> list[dict[str, Any]]:
        with self._lock:
            active = [
                row for row in self._rows
                if row["incident_id"] == incident_id
                and row["recommended_unit"] == recommended_unit
                and row["released_at"] is None
            ]
            claimed_ids = {row["station_id"] for row in active}
            for candidate in candidates:
                if len(active) >= required_count:
                    break
                if candidate["database_id"] in claimed_ids:
                    continue
                row = {
                    "id": self._next_id,
                    "incident_id": incident_id,
                    "recommended_unit": recommended_unit,
                    "station_id": candidate["database_id"],
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
                claimed_ids.add(row["station_id"])
            return [row.copy() for row in active]

    def release_incident(self, incident_id, *, released_at, reason):
        with self._lock:
            released = []
            for row in self._rows:
                if row["incident_id"] == incident_id and row["released_at"] is None:
                    row["released_at"] = released_at
                    row["release_reason"] = reason
                    released.append(row.copy())
            return released


def _fixed_response_plan(now: datetime) -> dict[str, Any]:
    """Mirror the successful Planner payload consumed by the allocator."""

    return {
        "metadata": {
            "planning_status": "success",
            "timestamp": now.isoformat(),
        },
        "event_id": "sample-haifa-fire",
        "location": DEMO_LOCATION,
        "responding_to": {
            "risk_score": 68.0,
            "risk_level": "medium",
            "risk_semantics": "detected_event_operational_risk",
        },
        "recommended_units": [
            "fire_department",
            "police",
            "medical_services",
        ],
        "response_actions": [
            {
                "action": "Dispatch emergency services to the detected fire.",
                "responsible_unit": "fire_department",
                "timeframe": "immediate",
            }
        ],
    }


def _allocation_summary(result: dict[str, Any]) -> dict[str, Any]:
    stations = [
        station
        for group in result.get("allocated_units", {}).values()
        for station in group
    ]
    return {
        "status": result.get("status", "failed"),
        "routing_status": result.get("routing_status", "not_available"),
        "requirements": result.get("requirements", {}),
        "shortages": result.get("shortages", {}),
        "stations": [
            {
                "database_id": station["database_id"],
                "name": station.get("name") or f"Station {station['database_id']}",
                "address": station.get("address"),
                "unit_type": station["unit_type"],
                "recommended_unit": station["recommended_unit"],
                "latitude": station["latitude"],
                "longitude": station["longitude"],
                "distance_km": station.get("distance_km"),
                "allocation_status": station.get("allocation_status", "assigned"),
                "selection_reason": station.get("selection_reason", "unknown"),
                "route": station.get("route"),
            }
            for station in stations
        ],
        "errors": [
            error for error in result.get("errors", []) if isinstance(error, dict)
        ],
        "settlement": result.get("settlement"),
    }


@lru_cache(maxsize=1)
def resource_allocation_demo_event() -> FireSharedEvent:
    """Run the real allocator once and expose its result as a shared event."""

    now = datetime.now(timezone.utc)
    agent = ResourceAllocationAgent(
        allocation_repository=DemoAllocationRepository(),
    )
    result = agent.allocate_batch([{
        "incident_id": DEMO_INCIDENT_ID,
        "queued_at": now,
        "response_plan": _fixed_response_plan(now),
    }], now=now)[0]

    return FireSharedEvent.model_validate({
        "id": DEMO_INCIDENT_ID,
        "type": "fire",
        "title": "Demo fire — Haifa",
        "description": (
            "Fixed development scenario used to preview assigned stations "
            "and Mapbox routes in the frontend."
        ),
        **DEMO_LOCATION,
        "observed_at": now,
        "classification": "emergency",
        "analysis_status": "success",
        "planning_status": "success",
        "details": {
            "detection_confidence": "high",
            "fire_weather_severity": "medium",
            "risk_score": 68.0,
            "risk_level": "medium",
            "confidence": "high",
            "primary_drivers": ["Fixed frontend allocation demo"],
            "explanation": "This is synthetic data and not an active incident.",
            "evidence_gaps": [],
            "recommended_units": [
                "fire_department",
                "police",
                "medical_services",
            ],
            "response_plan": ["Dispatch emergency services to the fire."],
            "response_actions": [{
                "action": "Dispatch emergency services to the detected fire.",
                "responsible_unit": "fire_department",
                "timeframe": "immediate",
            }],
            "protocol_citations": [],
            "resource_allocation": _allocation_summary(result),
        },
    })
