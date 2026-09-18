"""Generic post-Coordinator incident analysis and planning dispatch."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol
from uuid import uuid4

from ecoguard.coordinator import incidents as incident_store
from ecoguard.coordinator.queues import UnroutableHazard, queue_for

logger = logging.getLogger(__name__)

ProcessingStatus = Literal["success", "partial", "failed", "skipped"]


@dataclass(frozen=True)
class IncidentDispatchContext:
    """Coordinator-owned handoff metadata generated outside scientific evidence."""

    incident_id: str
    hazard: str
    route: str
    analysis_id: str
    coordinator_routing_id: str
    routed_by: str
    routed_at: datetime
    requested_at: datetime


@dataclass
class IncidentProcessingResult:
    """Runtime result ready for a future event projection, but not one itself."""

    incident_id: str
    hazard: str
    route: str
    status: ProcessingStatus
    requested_at: datetime
    completed_at: datetime
    analysis_id: str | None = None
    coordinator_routing_id: str | None = None
    handler: str | None = None
    analysis_status: str | None = None
    planner_status: str | None = None
    analysis_result: Any | None = None
    planner_result: Any | None = None
    failure_stage: str | None = None
    failure_reason: str | None = None
    resource_allocation_result: dict[str, Any] | None = None


class IncidentHandler(Protocol):
    """One hazard/route implementation behind the shared dispatch boundary."""

    name: str

    def process(
        self,
        incident: Mapping[str, Any],
        context: IncidentDispatchContext,
    ) -> IncidentProcessingResult: ...


HandlerRegistry = Mapping[tuple[str, str], IncidentHandler]
IncidentReader = Callable[[str], dict[str, Any] | None]


def _utc(value: datetime | None = None) -> datetime:
    supplied = value or datetime.now(timezone.utc)
    if supplied.tzinfo is None or supplied.utcoffset() is None:
        raise ValueError("dispatch time must carry a UTC offset")
    return supplied.astimezone(timezone.utc)


def default_handler_registry() -> dict[tuple[str, str], IncidentHandler]:
    """Production handlers, imported lazily so unsupported hazards stay cheap."""

    from ecoguard.analyzers.non_emergency.air_pollution.incident_handler import (
        configured_air_pollution_incident_handler,
    )

    return {
        ("air_pollution", "non_emergency"):
            configured_air_pollution_incident_handler(),
    }


def dispatch_incidents(
    incidents: Sequence[Mapping[str, Any]],
    *,
    registry: HandlerRegistry | None = None,
    at: datetime | None = None,
) -> list[IncidentProcessingResult]:
    """Dispatch each open incident facet independently and fail per handler."""

    requested_at = _utc(at)
    handlers = registry if registry is not None else default_handler_registry()
    results: list[IncidentProcessingResult] = []

    for incident in incidents:
        incident_id = str(incident.get("id") or "unknown")
        if incident.get("status") != "open":
            results.append(IncidentProcessingResult(
                incident_id=incident_id,
                hazard=str(incident.get("primary_hazard") or "unknown"),
                route="unrouted",
                status="skipped",
                requested_at=requested_at,
                completed_at=_utc(),
                failure_stage="dispatch",
                failure_reason="incident_not_open",
            ))
            continue

        hazards = list(dict.fromkeys(incident.get("hazards") or ()))
        incident_routes = set(incident.get("queues") or ())
        for hazard in hazards:
            try:
                route = queue_for(hazard)
            except UnroutableHazard:
                results.append(IncidentProcessingResult(
                    incident_id=incident_id,
                    hazard=hazard,
                    route="unrouted",
                    status="skipped",
                    requested_at=requested_at,
                    completed_at=_utc(),
                    failure_stage="dispatch",
                    failure_reason="unroutable_hazard",
                ))
                continue
            if route not in incident_routes:
                results.append(IncidentProcessingResult(
                    incident_id=incident_id,
                    hazard=hazard,
                    route=route,
                    status="skipped",
                    requested_at=requested_at,
                    completed_at=_utc(),
                    failure_stage="dispatch",
                    failure_reason="incident_route_mismatch",
                ))
                continue

            handler = handlers.get((hazard, route))
            if handler is None:
                results.append(IncidentProcessingResult(
                    incident_id=incident_id,
                    hazard=hazard,
                    route=route,
                    status="skipped",
                    requested_at=requested_at,
                    completed_at=_utc(),
                    failure_stage="dispatch",
                    failure_reason="unsupported_hazard_route",
                ))
                continue

            context = IncidentDispatchContext(
                incident_id=incident_id,
                hazard=hazard,
                route=route,
                analysis_id=f"analysis:{uuid4().hex}",
                coordinator_routing_id=f"routing:{uuid4().hex}",
                routed_by="shared_coordinator",
                routed_at=requested_at,
                requested_at=requested_at,
            )
            try:
                results.append(handler.process(incident, context))
            except Exception as error:
                logger.exception(
                    "incident %s handler %s failed", incident_id, handler.name
                )
                results.append(IncidentProcessingResult(
                    incident_id=incident_id,
                    hazard=hazard,
                    route=route,
                    status="failed",
                    requested_at=requested_at,
                    completed_at=_utc(),
                    analysis_id=context.analysis_id,
                    coordinator_routing_id=context.coordinator_routing_id,
                    handler=handler.name,
                    failure_stage="handler",
                    failure_reason=type(error).__name__,
                ))
    return results


def dispatch_touched(
    incident_ids: Sequence[str],
    *,
    registry: HandlerRegistry | None = None,
    incident_reader: IncidentReader = incident_store.incident_by_id,
    at: datetime | None = None,
) -> list[IncidentProcessingResult]:
    """Load only this Coordinator run's touched incidents, never a full rescan."""

    incidents = []
    results = []
    seen = set()
    requested_at = _utc(at)
    for incident_id in incident_ids:
        if incident_id in seen:
            continue
        seen.add(incident_id)
        incident = incident_reader(incident_id)
        if incident is None:
            results.append(IncidentProcessingResult(
                incident_id=incident_id,
                hazard="unknown",
                route="unrouted",
                status="skipped",
                requested_at=requested_at,
                completed_at=_utc(),
                failure_stage="load",
                failure_reason="incident_not_found",
            ))
        else:
            incidents.append(incident)
    return [
        *results,
        *dispatch_incidents(incidents, registry=registry, at=requested_at),
    ]
