"""Handing a finished fire plan to the resource allocator.

Translates the plan's unit types into the shape the allocator expects, and
carries the incident's location and severity with them. It decides nothing
about which station responds - that is the allocator's job.
"""

from __future__ import annotations

from typing import Any, Mapping

# The allocator keys its unit vocabulary on these. The planner speaks Israeli
# resource types; this is the one place the two vocabularies meet, and it is a
# mapping rather than a rename because they are not the same list: several
# planner types are appliances the allocator has no station category for.
RESOURCE_TO_ALLOCATOR_UNIT = {
    "fire_appliance": "fire_department",
    "water_tanker": "fire_department",
    "rapid_response_unit": "fire_department",
    "heavy_rescue": "fire_department",
    "leviathan": "fire_department",
    "smoke_pusher": "fire_department",
    "field_command": "fire_department",
    "police": "police",
    "mda": "medical_services",
}

# Resource types with no station to allocate from. Aerial assets are tasked
# through a different procedure entirely, and a standby squad is a settlement's
# own people. Listed so they are visibly excluded rather than silently dropped.
NOT_ALLOCATABLE = frozenset({
    "aerial_firefighting", "aerial_coordinator", "home_front_command",
    "kkl", "municipal_team", "idf_assistance", "standby_squad",
})

# Grade to the risk level the allocator's own vocabulary uses. Needed only
# because its request validation still checks one; the station counts come
# from the dispatch block, not from this.
GRADE_TO_RISK_LEVEL = {1: "low", 2: "medium", 3: "high", 4: "critical", 5: "critical"}

GRADE_TO_RISK_SCORE = {1: 20.0, 2: 45.0, 3: 70.0, 4: 88.0, 5: 100.0}


def build_allocation_request(
    result: Mapping[str, Any] | Any,
    *,
    queued_at: Any = None,
) -> dict[str, Any] | None:
    """One allocation request from one planner result.

    Args:
        result: a `PlannerResult`, or its dict form.
        queued_at: when the incident entered the queue. The allocator ages
            requests by this so an old one is not starved by a newer, larger
            fire — which is the contention behaviour it exists for.

    Returns:
        A request the allocator's `allocate_batch` accepts, or None when there
        is nothing to allocate. None rather than an empty request: a plan that
        failed and a plan that needs no appliances are different, and both
        would look identical as an empty allocation.
    """
    payload = result if isinstance(result, Mapping) else _as_dict(result)
    if payload.get("status") != "success":
        return None

    dispatch = payload.get("dispatch") or {}
    plan = payload.get("plan") or {}
    if dispatch.get("status") != "ok":
        return None

    grade = (dispatch.get("grade") or {}).get("grade")
    if grade not in GRADE_TO_RISK_LEVEL:
        return None

    # Unit types the allocator can actually put a station behind, in the order
    # the plan asked for them.
    requested: list[str] = []
    for request in plan.get("resource_requests") or ():
        resource = request.get("resource_type")
        if resource in NOT_ALLOCATABLE:
            continue
        unit = RESOURCE_TO_ALLOCATOR_UNIT.get(resource)
        if unit and unit not in requested:
            requested.append(unit)

    # Police and MDA are named by the dispatch block whether or not the model
    # asked for them, because the responsibility is jurisdictional and does
    # not depend on the plan remembering to mention it.
    if dispatch.get("police_notifications") and "police" not in requested:
        requested.append("police")
    if dispatch.get("mda_notifications") and "medical_services" not in requested:
        requested.append("medical_services")

    if not requested:
        return None

    # The responsible stations, so the allocator's road-time ranking cannot
    # quietly promote an out-of-district station over the home one.
    preferred = [
        {
            "name": station.get("name"),
            "district": station.get("district"),
            "teams": station.get("teams"),
            "role": station.get("role"),
            "request_type": station.get("request_type"),
        }
        for station in dispatch.get("stations") or ()
    ]

    return {
        "incident_id": payload.get("incident_id"),
        "queued_at": queued_at,
        # Shaped for the allocator's existing validation. `responding_to`
        # carries the semantics field it checks; the grade is what actually
        # decides the counts.
        "response_plan": {
            "metadata": {
                "planning_status": "success",
                "timestamp": payload.get("generated_at"),
            },
            "event_id": payload.get("incident_id"),
            "responding_to": {
                "risk_semantics": "detected_event_operational_risk",
                "risk_score": GRADE_TO_RISK_SCORE[grade],
                "risk_level": GRADE_TO_RISK_LEVEL[grade],
            },
            "recommended_units": requested,
            "response_actions": [
                {
                    "action": action.get("action"),
                    "responsible_unit": "fire_department",
                    "timeframe": action.get("timeframe"),
                }
                for action in plan.get("immediate_actions") or ()
            ],
            # Authoritative, and the reason this adapter exists.
            "dispatch_grade": grade,
            "teams_required": (dispatch.get("grade") or {}).get("teams_required"),
            "preferred_stations": preferred,
            "home_district": dispatch.get("home_district"),
        },
    }


def _as_dict(result: Any) -> dict[str, Any]:
    """A PlannerResult as a plain dict, without importing its module here."""
    dump = getattr(result, "model_dump", None)
    return dump(mode="json") if callable(dump) else dict(result)
