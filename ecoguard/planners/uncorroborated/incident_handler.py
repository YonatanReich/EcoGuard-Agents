"""Handling an incident that rests only on unconfirmed reports.

Routed here instead of to an analyzer, deliberately: there is no measurement to
analyse, and running one anyway would dress a rumour up as a finding."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from ecoguard.coordinator.dispatcher import (
    IncidentDispatchContext,
    IncidentProcessingResult,
)
from ecoguard.planners.uncorroborated.planner import (
    UncorroboratedReportPlanner,
    newest_claim,
)

logger = logging.getLogger(__name__)


class UncorroboratedReportHandler:
    """Advise on an unverified report. No analysis, no allocation, no model."""

    name = "UncorroboratedReportHandler"

    def __init__(self, *, planner: UncorroboratedReportPlanner | None = None) -> None:
        """Build the handler with its planner."""
        self._planner = planner or UncorroboratedReportPlanner()

    def process(
        self,
        incident: Mapping[str, Any],
        context: IncidentDispatchContext,
    ) -> IncidentProcessingResult:
        """Advise on one unconfirmed report.

        Skips analysis entirely: there is nothing measured to analyse, so the only
        useful answer is who to contact to find out.
        """
        claim, location_text = newest_claim(incident)

        advisory = self._planner.plan(
            hazard=context.hazard,
            latitude=incident.get("latitude"),
            longitude=incident.get("longitude"),
            claim=claim,
            location_text=location_text,
        )
        payload = advisory.as_dict()
        succeeded = advisory.status == "success"

        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            # Reported on its own route so nothing downstream can mistake this
            # for a normal advisory. The allocator reads `route` to decide what
            # to reserve against, and an unverified report reserves nothing.
            route="uncorroborated",
            status="success" if succeeded else "skipped",
            requested_at=context.requested_at,
            completed_at=datetime.now(timezone.utc),
            analysis_id=context.analysis_id,
            coordinator_routing_id=context.coordinator_routing_id,
            handler=self.name,
            analysis_status="skipped",
            risk_status="skipped",
            planner_status="success" if succeeded else "skipped",
            analysis_result=None,
            risk_assessment=None,
            planner_result=payload,
            failure_stage=None if succeeded else "planning",
            failure_reason=None if succeeded else advisory.reason,
            requires_resource_allocation=False,
        )


__all__ = ["UncorroboratedReportHandler"]
