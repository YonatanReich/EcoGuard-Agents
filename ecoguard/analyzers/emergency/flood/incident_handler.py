"""Flood handoff from the shared dispatcher to resource allocation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from ecoguard.coordinator.dispatcher import (
    IncidentDispatchContext,
    IncidentProcessingResult,
)
class FloodRoadIncidentHandler:
    """Mark a Flood incident ready for deterministic resource allocation."""

    name = "flood_emergency_allocation_handoff"

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._clock = clock

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Flood handler clock must carry a UTC offset")
        return value.astimezone(timezone.utc)

    def process(
        self,
        incident: Mapping[str, Any],
        context: IncidentDispatchContext,
    ) -> IncidentProcessingResult:
        if context.hazard != "flood" or context.route != "emergency":
            raise ValueError("Flood handler requires the emergency route")

        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            route=context.route,
            status="success",
            requested_at=context.requested_at,
            completed_at=self._now(),
            analysis_id=context.analysis_id,
            coordinator_routing_id=context.coordinator_routing_id,
            handler=self.name,
        )


@lru_cache(maxsize=1)
def configured_flood_road_incident_handler() -> FloodRoadIncidentHandler:
    """Build the deterministic Flood handler once per dispatcher process."""

    return FloodRoadIncidentHandler()


__all__ = [
    "FloodRoadIncidentHandler",
    "configured_flood_road_incident_handler",
]
