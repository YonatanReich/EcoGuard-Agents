"""Fire spread analysis followed by a grounded Israeli response plan.

The adapter the coordinator was missing. Everything either side of it already
existed — the spread analyser, the escalation and dispatch arithmetic, the
protocol corpus, the planner — and none of it was reachable, because
`default_handler_registry()` had no ("fire", "emergency") entry and a fire
incident came back `skipped / unsupported_hazard_route`.

Modelled on the Earthquake handler, which has the same shape: analyse, plan,
and report both outcomes separately so a failure in one is not read as a
failure of the other.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from ecoguard.analyzers.emergency.fire.spread_analyzer import analyze_incident
from ecoguard.coordinator.dispatcher import (
    IncidentDispatchContext,
    IncidentProcessingResult,
)
from ecoguard.database.repositories.responsible_services import responsible_services
from ecoguard.response_planner.fire.israeli_planner import plan_response

# A plan naming fifteen authorities is a plan nobody rings. The analyser has
# already sorted exposure worst-first, so taking the head takes the ones that
# matter.
MAX_SERVICE_LOOKUPS = 5


class FireIncidentHandler:
    """Turn a coordinator fire incident into an analysed, planned result."""

    name = "fire_spread_analysis_and_planning"

    def __init__(
        self,
        *,
        analyzer: Callable[..., Mapping[str, Any]] = analyze_incident,
        planner: Callable[..., Any] = plan_response,
        services_reader: Callable[[str], Mapping[str, Any]] = responsible_services,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        # Injected rather than imported at the call site so this is testable
        # without a database or a model call.
        self._analyzer = analyzer
        self._planner = planner
        self._services_reader = services_reader
        self._clock = clock

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Fire handler clock must carry a UTC offset")
        return value.astimezone(timezone.utc)

    def _services_for(
        self, analysis: Mapping[str, Any]
    ) -> list[Mapping[str, Any]]:
        """Who is responsible for each settlement the fire threatens.

        A lookup that fails is skipped rather than fatal: the planner is
        explicitly built to work from whichever contacts it is given, and one
        unreachable town should not cost the other four their plan.
        """
        records: list[Mapping[str, Any]] = []
        exposure: Sequence[Mapping[str, Any]] = analysis.get("exposure") or ()
        for item in exposure[:MAX_SERVICE_LOOKUPS]:
            locality_id = item.get("locality_id")
            if not locality_id:
                continue
            try:
                record = self._services_reader(str(locality_id))
            except Exception:
                continue
            if record.get("found"):
                records.append(record)
        return records

    def process(
        self,
        incident: Mapping[str, Any],
        context: IncidentDispatchContext,
    ) -> IncidentProcessingResult:
        if context.hazard != "fire" or context.route != "emergency":
            raise ValueError("Fire handler requires the emergency route")

        analysis = self._analyzer(incident)

        # The analyser reports "skipped" when it declined to assess — no
        # usable position, no environment, not a fire. That is an absence of
        # assessment, not a finding of safety, so it is carried through as a
        # skip with its own reason rather than flattened into a failure or
        # dressed up as a low-severity result.
        if analysis.get("status") != "ok":
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="partial",
                requested_at=context.requested_at,
                completed_at=self._now(),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                analysis_status="skipped",
                planner_status="skipped",
                analysis_result=analysis,
                failure_stage="analysis",
                failure_reason=str(
                    analysis.get("reason") or "fire_analysis_skipped"
                ),
            )

        plan = self._planner(analysis, services=self._services_for(analysis))
        planner_result = (
            plan.model_dump(mode="json")
            if hasattr(plan, "model_dump")
            else dict(plan)
        )
        planner_status = str(planner_result.get("status") or "failed")
        planned = planner_status == "success"

        # An analysed fire with no plan is still a real fire. It is reported
        # as partial with the analysis attached, so the projection can still
        # put it on the operator's map; withholding the event until a model
        # call succeeds would make the map depend on the least reliable step.
        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            route=context.route,
            status="success" if planned else "partial",
            requested_at=context.requested_at,
            completed_at=self._now(),
            analysis_id=context.analysis_id,
            coordinator_routing_id=context.coordinator_routing_id,
            handler=self.name,
            analysis_status="success",
            planner_status=planner_status,
            analysis_result=analysis,
            planner_result=planner_result,
            failure_stage=None if planned else "planning",
            failure_reason=(
                None
                if planned
                else str(planner_result.get("reason") or "fire_planning_failed")
            ),
        )


@lru_cache(maxsize=1)
def configured_fire_incident_handler() -> FireIncidentHandler:
    """Build the fire handler once per dispatcher process."""

    return FireIncidentHandler()


__all__ = [
    "FireIncidentHandler",
    "configured_fire_incident_handler",
]
