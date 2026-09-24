"""Deterministic Earthquake impact analysis followed by shared planning."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ecoguard.analyzers.earthquake.impact import estimate_impact
from ecoguard.coordinator.dispatcher import IncidentDispatchContext, IncidentProcessingResult
from ecoguard.planners.shared.adapters import build_earthquake_plan_input
from ecoguard.planners.shared.planner import EmergencyResponsePlanner


class EarthquakeIncidentHandler:
    name = "earthquake_impact_screening"

    def __init__(self, *, planner: object | None = None) -> None:
        """Build the handler with its planner."""
        self.planner = planner if planner is not None else EmergencyResponsePlanner()

    def process(
        self,
        incident: Mapping[str, Any],
        context: IncidentDispatchContext,
    ) -> IncidentProcessingResult:
        """Screen one earthquake and plan a response.

        The impact area is calculated, not modelled by a model; only the response
        plan involves one.
        """
        candidates = [
            signal["evidence"]["earthquake"]
            for signal in incident.get("signals") or []
            if (signal.get("evidence") or {}).get("earthquake")
        ]
        if not candidates:
            raise ValueError("earthquake_evidence_missing")
        earthquake = max(candidates, key=lambda item: item["observed_at"])
        impact = estimate_impact(earthquake)
        try:
            planner_input = build_earthquake_plan_input(
                impact,
                incident_id=context.incident_id,
            )
        except Exception as error:
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="partial",
                requested_at=context.requested_at,
                completed_at=datetime.now(timezone.utc),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                analysis_status="success",
                planner_status="skipped",
                analysis_result=impact,
                failure_stage="planning_input",
                failure_reason=type(error).__name__,
                requires_resource_allocation=False,
            )

        fallback_allocation_context = {
            "location": (
                planner_input.location.model_dump(mode="json")
                if planner_input.location is not None
                else None
            ),
            "risk_context": dict(planner_input.risk_context or {}),
        }
        try:
            plan = self.planner.plan_response(planner_input)
        except Exception as error:
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="partial",
                requested_at=context.requested_at,
                completed_at=datetime.now(timezone.utc),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                analysis_status="success",
                planner_status="failed",
                analysis_result=impact,
                fallback_allocation_context=fallback_allocation_context,
                failure_stage="planning",
                failure_reason=type(error).__name__,
                requires_resource_allocation=True,
            )
        planner_result = (
            plan.model_dump(mode="json")
            if hasattr(plan, "model_dump")
            else dict(plan)
        )
        planner_status = str(
            (planner_result.get("metadata") or {}).get("planning_status")
            or "failed"
        )
        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            route=context.route,
            status="success" if planner_status == "success" else "partial",
            requested_at=context.requested_at,
            completed_at=datetime.now(timezone.utc),
            analysis_id=context.analysis_id,
            coordinator_routing_id=context.coordinator_routing_id,
            handler=self.name,
            analysis_status="success",
            planner_status=planner_status,
            analysis_result=impact,
            planner_result=planner_result,
            fallback_allocation_context=(
                fallback_allocation_context
                if planner_status in {"failed", "skipped"}
                else None
            ),
            failure_stage=(None if planner_status == "success" else "planning"),
            failure_reason=(
                None
                if planner_status == "success"
                else planner_result.get("error")
                or (planner_result.get("metadata") or {}).get("reason")
                or "earthquake_planning_failed"
            ),
            requires_resource_allocation=(
                planner_status in {"success", "failed", "skipped"}
            ),
        )
