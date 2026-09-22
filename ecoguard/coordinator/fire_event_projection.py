"""Project the active Fire pipeline into the frontend SharedEvent contract."""

from __future__ import annotations

from typing import Any, Mapping

from ecoguard.shared.events import (
    FireDetails,
    FireResponseAction,
    FireSharedEvent,
    ProtocolCitation,
)


def fire_shared_event(
    detected_event: Mapping[str, Any],
    risk_assessment: Mapping[str, Any] | None = None,
    planner: Mapping[str, Any] | None = None,
    *,
    incident_id: str,
) -> FireSharedEvent:
    """Project DetectedFireEvent, RiskAnalysisAgent and emergency-plan output."""

    risk = risk_assessment or {}
    plan = planner or {}
    location = detected_event.get("location") or {}
    latitude = float(location["latitude"])
    longitude = float(location["longitude"])
    geospatial = detected_event.get("geospatial_context") or {}
    settlements = geospatial.get("nearby_settlements") or ()
    named_settlement = next(
        (
            str(item["name"])
            for item in settlements
            if isinstance(item, Mapping) and item.get("name")
        ),
        None,
    )
    title = (
        f"Fire detected near {named_settlement}"
        if named_settlement
        else f"Fire at {latitude:.3f}, {longitude:.3f}"
    )

    response_actions = [
        FireResponseAction.model_validate(item)
        for item in plan.get("response_actions") or ()
    ]
    citations = [
        ProtocolCitation.model_validate(item)
        for item in [
            *((risk.get("grounding") or {}).get("citations") or ()),
            *((plan.get("grounding") or {}).get("citations") or ()),
        ]
    ]
    risk_status = str(
        (risk.get("metadata") or {}).get("analysis_status") or "failed"
    )
    planning_status = str(
        (plan.get("metadata") or {}).get("planning_status") or "skipped"
    )
    valid_statuses = {"success", "partial", "unavailable", "failed", "skipped"}
    if risk_status not in valid_statuses:
        risk_status = "failed"
    if planning_status not in valid_statuses:
        planning_status = "failed"

    details = FireDetails(
        detection_confidence=detected_event.get("detection_confidence"),
        fire_weather_severity=detected_event.get("fire_weather_severity"),
        risk_score=risk.get("risk_score"),
        risk_level=risk.get("risk_level"),
        confidence=risk.get("confidence"),
        primary_drivers=list(risk.get("primary_drivers") or ()),
        explanation=risk.get("explanation"),
        assumptions=list(plan.get("assumptions") or ()),
        evidence_gaps=list(dict.fromkeys([
            *[str(item) for item in risk.get("evidence_gaps") or ()],
            *[str(item) for item in plan.get("evidence_gaps") or ()],
        ])),
        limitations=list(dict.fromkeys([
            *[str(item) for item in risk.get("limitations") or ()],
            *[str(item) for item in plan.get("limitations") or ()],
        ])),
        recommended_units=list(plan.get("recommended_units") or ()),
        response_plan=[item.action for item in response_actions],
        response_actions=response_actions,
        protocol_citations=citations,
        incident_report=risk.get("explanation"),
    )
    return FireSharedEvent(
        id=incident_id,
        title=title,
        description=(
            plan.get("plan_summary")
            or risk.get("explanation")
            or "A fire incident was detected; operational analysis is unavailable."
        ),
        latitude=latitude,
        longitude=longitude,
        observed_at=None,
        classification="emergency",
        analysis_status=risk_status,
        planning_status=planning_status,
        details=details,
    )


__all__ = ["fire_shared_event"]
