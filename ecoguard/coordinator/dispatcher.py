"""Generic post-Coordinator incident analysis and planning dispatch."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol
from uuid import uuid4

from ecoguard.coordinator import incidents as incident_store
from ecoguard.coordinator.queues import UnroutableHazard, queue_for
from ecoguard.database.repositories.event_projections import (
    event_projection_by_incident,
)

logger = logging.getLogger(__name__)

ProcessingStatus = Literal["success", "partial", "failed", "skipped"]

# How long a successful plan stands before a routine re-dispatch may rebuild it.
#
# An open incident is "touched" every time another routine signal lands on it,
# and the air pollution and earthquake handlers rebuild their plan on every
# touch. One air quality episode took 140 signals in under five hours, each one
# a fresh model call describing a situation that had not changed.
#
# ponytail: a clock, not a change detector. It cannot tell a worsening event
# from a steady one, so a genuine escalation waits out the window before its
# plan is rebuilt. The upgrade path is the flood handler's
# `_response_refresh_required` — an analysis-aware gate that re-plans on
# escalation and skips otherwise. Flood already has it and is unaffected by
# this; port it per hazard and the clock stops mattering.
PLAN_REFRESH_MINUTES = int(os.getenv("ECOGUARD_PLAN_REFRESH_MINUTES", "60"))

ProjectionReader = Callable[[str], dict[str, Any] | None]


def plan_is_fresh(
    incident_id: str,
    now: datetime,
    reader: ProjectionReader,
) -> bool:
    """Whether this incident already carries a recent successful plan.

    Only a *successful* projection counts. A failed or never-planned incident
    is dispatched immediately, so a new incident and a retry after an outage
    are both unaffected.
    """
    try:
        projection = reader(incident_id)
    except Exception:
        # The gate is an optimisation. If the store cannot answer, dispatch.
        logger.exception("plan freshness check failed for %s; dispatching", incident_id)
        return False

    if projection is None:
        return False

    last_success = projection.get("last_success_at")
    if last_success is None:
        return False

    return now - last_success < timedelta(minutes=PLAN_REFRESH_MINUTES)


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
    risk_status: str | None = None
    planner_status: str | None = None
    analysis_result: Any | None = None
    risk_assessment: Any | None = None
    planner_result: Any | None = None
    failure_stage: str | None = None
    failure_reason: str | None = None
    resource_allocation_result: dict[str, Any] | None = None
    response_refresh_required: bool | None = None
    requires_resource_allocation: bool | None = None
    preserve_existing_response: bool = False


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
    from ecoguard.analyzers.emergency.earthquake.incident_handler import (
        EarthquakeIncidentHandler,
    )
    from ecoguard.analyzers.emergency.flood.incident_handler import (
        configured_flood_road_incident_handler,
    )
    from ecoguard.analyzers.emergency.fire.incident_handler import (
        configured_fire_incident_handler,
    )

    return {
        ("air_pollution", "non_emergency"):
            configured_air_pollution_incident_handler(),
        ("earthquake", "emergency"): EarthquakeIncidentHandler(),
        ("fire", "emergency"): configured_fire_incident_handler(),
        ("flood", "emergency"): configured_flood_road_incident_handler(),
    }


def dispatch_incidents(
    incidents: Sequence[Mapping[str, Any]],
    *,
    registry: HandlerRegistry | None = None,
    at: datetime | None = None,
    projection_reader: ProjectionReader = event_projection_by_incident,
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

            if plan_is_fresh(incident_id, requested_at, projection_reader):
                # No result is appended on purpose: an incident nobody
                # re-planned must keep the projection it already has, and must
                # not be re-allocated either.
                logger.debug(
                    "incident %s (%s) skipped: plan is under %s minutes old",
                    incident_id, hazard, PLAN_REFRESH_MINUTES,
                )
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
    projection_reader: ProjectionReader = event_projection_by_incident,
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
        *dispatch_incidents(
            incidents,
            registry=registry,
            at=requested_at,
            projection_reader=projection_reader,
        ),
    ]
