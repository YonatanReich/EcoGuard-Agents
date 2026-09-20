"""Deterministic earthquake incident handler; no planner or model calls."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ecoguard.analyzers.emergency.earthquake.impact import estimate_impact
from ecoguard.coordinator.dispatcher import IncidentDispatchContext, IncidentProcessingResult


class EarthquakeIncidentHandler:
    name = "earthquake_impact_screening"

    def process(
        self,
        incident: Mapping[str, Any],
        context: IncidentDispatchContext,
    ) -> IncidentProcessingResult:
        candidates = [
            signal["evidence"]["earthquake"]
            for signal in incident.get("signals") or []
            if (signal.get("evidence") or {}).get("earthquake")
        ]
        if not candidates:
            raise ValueError("earthquake_evidence_missing")
        earthquake = max(candidates, key=lambda item: item["observed_at"])
        impact = estimate_impact(earthquake)
        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            route=context.route,
            status="success",
            requested_at=context.requested_at,
            completed_at=datetime.now(timezone.utc),
            analysis_id=context.analysis_id,
            coordinator_routing_id=context.coordinator_routing_id,
            handler=self.name,
            analysis_status="success",
            planner_status="skipped",
            analysis_result=impact,
        )
