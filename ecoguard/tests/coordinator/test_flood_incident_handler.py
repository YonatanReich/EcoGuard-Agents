"""Flood allocation handoff at the shared incident-dispatch boundary."""

from datetime import datetime, timezone
from ecoguard.analyzers.emergency.flood.incident_handler import (
    FloodRoadIncidentHandler,
)
from ecoguard.coordinator.dispatcher import dispatch_incidents


AT = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _incident():
    return {
        "id": "INC-FLOOD-1",
        "status": "open",
        "primary_hazard": "flood",
        "hazards": ["flood"],
        "queues": ["emergency"],
        "signals": [],
    }


def _dispatch():
    handler = FloodRoadIncidentHandler(clock=lambda: AT)
    result = dispatch_incidents(
        [_incident()],
        registry={("flood", "emergency"): handler},
        at=AT,
    )[0]
    return result


def test_handler_preserves_incident_for_the_resource_allocator():
    result = _dispatch()

    assert result.status == "success"
    assert result.handler == "flood_emergency_allocation_handoff"
    assert result.resource_allocation_result is None
    assert result.allocation_input == {"incident": _incident()}
