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

# What a retryable failure costs, and why it is now bounded.
#
# Until this existed, a retryable failure was dispatched again on the very next
# tick, forever. That is not a theoretical hazard: on 2026-09-22 the projection
# table held 25 air-pollution incidents with 209 dispatch attempts between them,
# 205 of those retryable and 19 incidents that had never once succeeded after up
# to 19 attempts each. One tick at 05:53:30 dispatched 13 incidents at once.
# Every one of those attempts was a paid Sonnet call describing a situation that
# had not changed, for a plan that could not succeed.
#
# The loop closed because nothing in it was self-limiting. A pollution station
# re-signals every few minutes, so the incident is "touched" on every tick; the
# incident stays open for its 18-hour quiet period; and a failed plan set
# retryable=True, which was the one flag that bypassed the freshness gate
# entirely. Signal rate drove model spend directly, which is exactly the
# coupling the freshness gate exists to break.
#
# So retries now back off geometrically from the tick interval and stop after a
# handful. Both numbers are read from the projection row the writer already
# maintains — attempt_count and last_attempt_at — so this needs no new state.
PLAN_RETRY_BASE_MINUTES = int(os.getenv("ECOGUARD_PLAN_RETRY_BASE_MINUTES", "10"))

# After this many failed attempts the incident is left alone until it closes.
# A plan that has failed six times is failing for a structural reason — an
# ungroundable corpus, a schema the model cannot satisfy, a dead key — and none
# of those are fixed by a seventh identical call. Six attempts under the backoff
# below spans roughly five hours, which is most of an incident's useful life.
PLAN_MAX_RETRY_ATTEMPTS = int(os.getenv("ECOGUARD_PLAN_MAX_RETRY_ATTEMPTS", "6"))

ProjectionReader = Callable[[str], dict[str, Any] | None]


def plan_is_fresh(
    incident_id: str,
    now: datetime,
    reader: ProjectionReader,
) -> bool:
    """Whether this incident's last outcome is recent enough to stand.

    A recent success stands. So does a recent outcome that is not retryable —
    a partial analysis whose plan succeeded, or a plan skipped because policy
    says the event is never shown: nothing about it changes on the next tick,
    so re-running it every ten minutes only churns the projection.

    A retryable failure (model outage, planning error) is dispatched again, but
    on a geometric backoff and only PLAN_MAX_RETRY_ATTEMPTS times — see the
    constants above for what an unbounded retry actually cost. An incident with
    no projection yet has never been attempted and is always dispatched.
    """
    try:
        projection = reader(incident_id)
    except Exception:
        # The gate is an optimisation. If the store cannot answer, dispatch.
        logger.exception("plan freshness check failed for %s; dispatching", incident_id)
        return False

    if projection is None:
        return False

    window = timedelta(minutes=PLAN_REFRESH_MINUTES)

    last_success = projection.get("last_success_at")
    if last_success is not None and now - last_success < window:
        return True

    last_attempt = projection.get("last_attempt_at")

    if projection.get("retryable"):
        # Never attempted, or a writer that did not record when: dispatch and
        # let this same gate bound the next one.
        if last_attempt is None:
            return False
        return not _retry_is_due(incident_id, projection, now, last_attempt)

    if last_attempt is None:
        return False

    return now - last_attempt < window


def _retry_is_due(
    incident_id: str,
    projection: dict[str, Any],
    now: datetime,
    last_attempt: datetime,
) -> bool:
    """Whether a retryable failure has waited long enough to be worth paying for.

    The delay doubles per attempt from PLAN_RETRY_BASE_MINUTES, so a plan that
    keeps failing costs a call at roughly 10, 20, 40, 80 and 160 minutes rather
    than one every tick. After PLAN_MAX_RETRY_ATTEMPTS it is never due again and
    the incident rides out its quiet period on whatever it last projected.
    """
    attempts = projection.get("attempt_count")
    attempts = int(attempts) if isinstance(attempts, (int, float)) else 0

    if attempts >= PLAN_MAX_RETRY_ATTEMPTS:
        logger.warning(
            "incident %s abandoned after %s failed attempts (%s); "
            "no further model calls until it closes",
            incident_id,
            attempts,
            projection.get("failure_reason") or projection.get("planner_status"),
        )
        return False

    # attempts is 1 after the first write, so the first retry waits one base
    # interval rather than none.
    delay = timedelta(minutes=PLAN_RETRY_BASE_MINUTES * 2 ** max(attempts - 1, 0))
    due = now - last_attempt >= delay

    if not due:
        logger.debug(
            "incident %s retry %s not due: waiting %s from %s",
            incident_id, attempts + 1, delay, last_attempt,
        )
    return due


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
    ) -> IncidentProcessingResult:
        """Analyse and plan for one incident, and report what happened.

        Never raises: a handler that fails returns a result saying so, because
        one broken hazard must not stop the others in the same wave.
        """
        ...


HandlerRegistry = Mapping[tuple[str, str], IncidentHandler]
IncidentReader = Callable[[str], dict[str, Any] | None]


def _utc(value: datetime | None = None) -> datetime:
    """Normalise a time to UTC, refusing one that carries no timezone.

    A naive datetime here would silently compare wrong against stored times,
    so it is rejected rather than assumed to be UTC.
    """
    supplied = value or datetime.now(timezone.utc)
    if supplied.tzinfo is None or supplied.utcoffset() is None:
        raise ValueError("dispatch time must carry a UTC offset")
    return supplied.astimezone(timezone.utc)


# The variable every text-derived signal carries; anything else is an
# instrument reading. Duplicated from the triage module rather than imported,
# so the coordinator does not take a dependency on a detector.
TEXT_VARIABLE = "report"

# Registry key for the one handler that takes uncorroborated reports of any
# hazard. Not a (hazard, route) pair, because the whole point is that it does
# not vary by either.
UNCORROBORATED_ROUTE = ("*", "uncorroborated")


def is_uncorroborated_report(incident: Mapping[str, Any]) -> bool:
    """Whether this incident rests entirely on claims nobody has confirmed.

    True when every signal is a text report and none of them was corroborated.
    A single hotspot, gauge reading or second independent claim flips it false,
    which is what makes the upgrade automatic: nothing rewrites the incident, it
    simply stops meeting this test and the next dispatch sends it down the
    ordinary analyse-then-plan path.

    An incident with no readable signals is not treated as uncorroborated — it
    is not evidence of a rumour either, and the hazard handler is still the
    right place to decide what to do with it.
    """
    signals = [
        signal for signal in incident.get("signals") or ()
        if isinstance(signal, Mapping)
    ]
    if not signals:
        return False

    for signal in signals:
        if signal.get("variable") != TEXT_VARIABLE:
            return False
        report = (signal.get("evidence") or {}).get("text_report")
        if not isinstance(report, Mapping) or report.get("corroborated"):
            return False
    return True


def default_handler_registry() -> dict[tuple[str, str], IncidentHandler]:
    """Production handlers, imported lazily so unsupported hazards stay cheap."""

    from ecoguard.analyzers.air_pollution.incident_handler import (
        configured_air_pollution_incident_handler,
    )
    from ecoguard.analyzers.earthquake.incident_handler import (
        EarthquakeIncidentHandler,
    )
    from ecoguard.analyzers.flood.incident_handler import (
        configured_flood_road_incident_handler,
    )
    from ecoguard.analyzers.fire.incident_handler import (
        configured_fire_incident_handler,
    )
    from ecoguard.planners.uncorroborated.incident_handler import (
        UncorroboratedReportHandler,
    )

    return {
        ("air_pollution", "non_emergency"):
            configured_air_pollution_incident_handler(),
        ("earthquake", "emergency"): EarthquakeIncidentHandler(),
        ("fire", "emergency"): configured_fire_incident_handler(),
        ("flood", "emergency"): configured_flood_road_incident_handler(),
        UNCORROBORATED_ROUTE: UncorroboratedReportHandler(),
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

            # An uncorroborated report is handled the same way whatever it
            # claims to be, so it is matched before the hazard registry. There
            # is nothing to analyse in an unconfirmed claim, and a risk score
            # computed from one would be presented to an operator with exactly
            # the same weight as a score computed from a satellite.
            if is_uncorroborated_report(incident):
                handler = handlers.get(UNCORROBORATED_ROUTE)
            else:
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
