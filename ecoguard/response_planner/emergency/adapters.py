"""Adapters from existing analyzer outputs into the shared planning contract."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_event_id
from ecoguard.response_planner.emergency.schemas import EmergencyResponsePlanInput


class OperationalAnalysisUnavailable(ValueError):
    """The event lacks a successful, semantically valid operational analysis."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def build_fire_plan_input(
    detected_event: Mapping[str, Any],
    risk_assessment: Mapping[str, Any],
    *,
    spread_analysis: Mapping[str, Any] | None = None,
) -> EmergencyResponsePlanInput:
    """Adapt current Fire detection and operational-risk output without re-analysis."""

    event = _mapping(detected_event)
    risk = _mapping(risk_assessment)
    metadata = _mapping(risk.get("metadata"))
    if (
        event.get("event_type") != "fire"
        or event.get("detected") is not True
        or metadata.get("analysis_status") != "success"
        or risk.get("risk_semantics") != "detected_event_operational_risk"
        or isinstance(risk.get("risk_score"), bool)
        or not isinstance(risk.get("risk_score"), int)
        or not 0 <= risk["risk_score"] <= 100
        or risk.get("risk_level") not in {"low", "medium", "high", "critical"}
        or risk.get("confidence") not in {"low", "medium", "high"}
    ):
        raise OperationalAnalysisUnavailable("risk_analysis_unavailable")

    location = _mapping(risk.get("location")) or _mapping(event.get("location"))
    summary = risk.get("explanation")
    if not isinstance(summary, str) or not summary.strip():
        raise OperationalAnalysisUnavailable("risk_analysis_unavailable")

    additional_context: dict[str, Any] = {
        # Kept nested because these shapes are Fire-specific and are also used
        # by the compatibility wrapper's established retrieval/prompt logic.
        "detected_event": event,
        "risk_assessment": risk,
        "situational_context": risk.get("situational_context"),
        "primary_drivers": list(risk.get("primary_drivers") or []),
        "web_findings": list(risk.get("web_findings") or []),
    }
    limitations = list(risk.get("limitations") or [])
    if spread_analysis is not None:
        spread = _mapping(spread_analysis)
        additional_context["fire_spread_forecast"] = spread
        limitations.extend(str(item) for item in spread.get("limits") or [])

    description_parts = [summary.strip()]
    if risk.get("risk_score") is not None:
        description_parts.append(f"Operational risk score: {risk['risk_score']} out of 100.")
    if risk.get("risk_level"):
        description_parts.append(f"Operational risk level: {risk['risk_level']}.")
    if risk.get("confidence"):
        description_parts.append(f"Assessment confidence: {risk['confidence']}.")
    drivers = risk.get("primary_drivers") or []
    if drivers:
        description_parts.append(
            "Primary drivers: " + "; ".join(str(item) for item in drivers) + "."
        )
    situational = risk.get("situational_context")
    if isinstance(situational, Mapping) and situational:
        description_parts.append(
            "Situational context: "
            + json.dumps(dict(situational), ensure_ascii=False, sort_keys=True)
            + "."
        )

    try:
        return EmergencyResponsePlanInput(
            # Preserve the established Fire wire identity. The legacy planner
            # has always identified the plan from the detected event itself;
            # a stale or mismatched assessment id must not silently retarget it.
            incident_id=build_event_id(event),
            hazard_type="fire",
            location=location,
            event_description=" ".join(description_parts),
            risk_context={
                "risk_score": risk.get("risk_score"),
                "risk_level": risk.get("risk_level"),
                "risk_semantics": risk.get("risk_semantics"),
                "confidence": risk.get("confidence"),
            },
            evidence_gaps=[str(item) for item in risk.get("evidence_gaps") or []],
            limitations=limitations,
            additional_context=additional_context,
        )
    except (TypeError, ValueError) as error:
        raise OperationalAnalysisUnavailable("risk_analysis_unavailable") from error
