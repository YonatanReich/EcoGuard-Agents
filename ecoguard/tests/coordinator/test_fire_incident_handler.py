"""The fire handler's three outcomes, with the analyser and planner injected.

No database and no model call: the point of these is the handoff contract —
which status the dispatcher sees, and whether the analysis survives a planning
failure — not the physics or the plan text, which have their own suites.
"""

from datetime import datetime, timezone

import pytest

from ecoguard.analyzers.emergency.fire.incident_handler import FireIncidentHandler
from ecoguard.coordinator.dispatcher import IncidentDispatchContext

AT = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)

CONTEXT = IncidentDispatchContext(
    incident_id="INC-FIRE-1",
    hazard="fire",
    route="emergency",
    analysis_id="AN-1",
    coordinator_routing_id="RT-1",
    routed_by="test",
    routed_at=AT,
    requested_at=AT,
)

ANALYSED = {
    "status": "ok",
    "incident_id": "INC-FIRE-1",
    "risk_level": "high",
    "risk_score": 78,
    "exposure": [
        {"locality_id": "T1", "name": "Nir Etzion"},
        {"locality_id": None, "name": "unnamed"},
    ],
}


def _handler(analysis, plan, *, services=None):
    return FireIncidentHandler(
        analyzer=lambda incident: analysis,
        planner=lambda a, services=(): plan,
        services_reader=(services or (lambda town_id: {"found": True, "town_id": town_id})),
        clock=lambda: AT,
    )


def test_a_planned_fire_is_a_success_carrying_both_results():
    handler = _handler(ANALYSED, {"status": "success", "plan": {"a": 1}})

    result = handler.process({"id": "INC-FIRE-1"}, CONTEXT)

    assert result.status == "success"
    assert result.analysis_status == "success"
    assert result.planner_status == "success"
    assert result.analysis_result == ANALYSED
    assert result.planner_result["plan"] == {"a": 1}
    assert result.failure_stage is None


def test_a_failed_plan_still_reports_the_analysis():
    """A fire nobody could plan for is still a fire the operator must see."""
    handler = _handler(
        ANALYSED, {"status": "failed", "reason": "llm_unavailable"}
    )

    result = handler.process({"id": "INC-FIRE-1"}, CONTEXT)

    assert result.status == "partial"
    assert result.analysis_status == "success"
    assert result.analysis_result == ANALYSED  # not discarded with the plan
    assert result.planner_status == "failed"
    assert result.failure_stage == "planning"
    assert result.failure_reason == "llm_unavailable"


def test_a_skipped_analysis_is_a_skip_and_not_a_low_severity_result():
    """Absence of assessment must not read as a finding of safety."""
    skipped = {
        "status": "skipped",
        "reason": "environment_unavailable",
        "risk_score": None,
        "risk_level": None,
    }
    handler = _handler(skipped, {"status": "success"})

    result = handler.process({"id": "INC-FIRE-1"}, CONTEXT)

    assert result.status == "partial"
    assert result.analysis_status == "skipped"
    assert result.planner_status == "skipped"
    assert result.failure_stage == "analysis"
    assert result.failure_reason == "environment_unavailable"
    assert result.planner_result is None


def test_only_locatable_settlements_are_looked_up():
    """The exposure row with no locality_id must not reach the reader."""
    asked: list[str] = []

    handler = _handler(
        ANALYSED,
        {"status": "success"},
        services=lambda town_id: (
            asked.append(town_id) or {"found": True, "town_id": town_id}
        ),
    )
    handler.process({"id": "INC-FIRE-1"}, CONTEXT)

    assert asked == ["T1"]


def test_a_service_lookup_failure_does_not_cost_the_plan():
    """One unreachable town should not deny the other settlements a plan."""

    def exploding(town_id):
        raise RuntimeError("store unavailable")

    handler = _handler(ANALYSED, {"status": "success"}, services=exploding)

    result = handler.process({"id": "INC-FIRE-1"}, CONTEXT)

    assert result.status == "success"


def test_the_handler_refuses_a_route_it_does_not_own():
    handler = _handler(ANALYSED, {"status": "success"})
    context = IncidentDispatchContext(
        incident_id="INC-1",
        hazard="flood",
        route="emergency",
        analysis_id="AN-1",
        coordinator_routing_id="RT-1",
        routed_by="test",
        routed_at=AT,
        requested_at=AT,
    )

    with pytest.raises(ValueError):
        handler.process({"id": "INC-1"}, context)
