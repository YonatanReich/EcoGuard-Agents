"""Shared, fail-closed emergency response planning for analyzed incidents."""

from ecoguard.response_planner.emergency.adapters import (
    OperationalAnalysisUnavailable,
    build_fire_plan_input,
    build_flood_plan_input,
)
from ecoguard.response_planner.emergency.planner import EmergencyResponsePlanner
from ecoguard.response_planner.emergency.schemas import (
    EmergencyResponsePlan,
    EmergencyResponsePlanInput,
)

__all__ = [
    "EmergencyResponsePlan",
    "EmergencyResponsePlanInput",
    "EmergencyResponsePlanner",
    "OperationalAnalysisUnavailable",
    "build_fire_plan_input",
    "build_flood_plan_input",
]
