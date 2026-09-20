"""Flood analysis and protocol-planning orchestration behind the dispatcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from ecoguard.analyzers.emergency.flood.event_analyzer import FloodEventAnalyzer
from ecoguard.response_planner.emergency.adapters import (
    OperationalAnalysisUnavailable,
    build_flood_plan_input,
)
from ecoguard.response_planner.emergency.planner import EmergencyResponsePlanner
from ecoguard.coordinator.dispatcher import (
    IncidentDispatchContext,
    IncidentProcessingResult,
)


class FloodRoadIncidentHandler:
    """Analyze Flood evidence and refresh response only for actionable change."""

    name = "flood_emergency_analysis_planning"

    def __init__(
        self,
        *,
        analyzer: FloodEventAnalyzer | None = None,
        planner: EmergencyResponsePlanner | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._analyzer = analyzer or FloodEventAnalyzer(clock=clock)
        self._planner = planner or EmergencyResponsePlanner()
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

        try:
            analysis = self._analyzer.analyze(incident)
        except Exception as error:
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="failed",
                requested_at=context.requested_at,
                completed_at=self._now(),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                failure_stage="analysis",
                failure_reason=type(error).__name__,
                response_refresh_required=False,
                requires_resource_allocation=False,
                preserve_existing_response=True,
            )

        refresh = self._response_refresh_required(analysis)
        if not refresh:
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status=("partial" if analysis.status == "unavailable" else "success"),
                requested_at=context.requested_at,
                completed_at=self._now(),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                analysis_status=analysis.status,
                analysis_result=analysis,
                planner_status="skipped",
                response_refresh_required=False,
                requires_resource_allocation=False,
                preserve_existing_response=True,
            )

        try:
            plan_input = build_flood_plan_input(analysis)
            plan = self._planner.plan_response(plan_input)
        except OperationalAnalysisUnavailable as error:
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
                analysis_status=analysis.status,
                analysis_result=analysis,
                failure_stage="planning_input",
                failure_reason=str(error),
                response_refresh_required=True,
                requires_resource_allocation=True,
            )
        except Exception as error:
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
                analysis_status=analysis.status,
                analysis_result=analysis,
                failure_stage="planning",
                failure_reason=type(error).__name__,
                response_refresh_required=True,
                requires_resource_allocation=True,
            )

        planner_status = plan.metadata.planning_status
        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            route=context.route,
            status=(
                "success"
                if analysis.status == "success" and planner_status == "success"
                else "partial"
            ),
            requested_at=context.requested_at,
            completed_at=self._now(),
            analysis_id=context.analysis_id,
            coordinator_routing_id=context.coordinator_routing_id,
            handler=self.name,
            analysis_status=analysis.status,
            planner_status=planner_status,
            analysis_result=analysis,
            planner_result=plan.model_dump(mode="json"),
            response_refresh_required=True,
            # Deterministic Flood allocation remains available even when the
            # protocol planner fails closed or credentials are unavailable.
            requires_resource_allocation=True,
        )

    @staticmethod
    def _response_refresh_required(analysis) -> bool:
        change = analysis.change_assessment
        if change is None:
            return False
        return bool(
            change.change_type in {"initial", "escalated"}
            or change.new_station_ids
            or change.new_cell_ids
        )


@lru_cache(maxsize=1)
def configured_flood_road_incident_handler() -> FloodRoadIncidentHandler:
    """Build the Flood analysis/planning stack once per dispatcher process."""

    return FloodRoadIncidentHandler()


__all__ = [
    "FloodRoadIncidentHandler",
    "configured_flood_road_incident_handler",
]
