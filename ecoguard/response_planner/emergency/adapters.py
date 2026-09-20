"""Adapters from existing analyzer outputs into the shared planning contract."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_event_id
from ecoguard.analyzers.emergency.flood.event_analysis_schemas import (
    FloodEventAnalysis,
)
from ecoguard.analyzers.emergency.flood.risk_analysis_schemas import (
    FloodRiskAssessment,
)
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


def build_flood_plan_input(
    analysis: FloodEventAnalysis | Mapping[str, Any],
    risk_assessment: FloodRiskAssessment | Mapping[str, Any],
) -> EmergencyResponsePlanInput:
    """Adapt event and risk outputs without recalculating either one."""

    try:
        validated = FloodEventAnalysis.model_validate(analysis)
    except (TypeError, ValueError, AttributeError) as error:
        raise OperationalAnalysisUnavailable("flood_analysis_unavailable") from error
    try:
        risk = FloodRiskAssessment.model_validate(risk_assessment)
    except (TypeError, ValueError, AttributeError) as error:
        raise OperationalAnalysisUnavailable("flood_risk_unavailable") from error

    state = validated.current_state
    change = validated.change_assessment
    progression = validated.progression_assessment
    if validated.status == "unavailable" or state is None or change is None:
        raise OperationalAnalysisUnavailable("flood_analysis_unavailable")
    if (
        risk.event_id != validated.incident_id
        or risk.event_type != "flood"
        or risk.metadata.analysis_status not in {"success", "partial"}
        or risk.risk_score is None
        or risk.risk_level is None
        or risk.hydrologic_severity_level != state.severity_level
    ):
        raise OperationalAnalysisUnavailable("flood_risk_unavailable")

    primary = next(
        (
            station
            for station in state.stations
            if station.station_id == state.primary_station_id
        ),
        None,
    )
    location = (
        {"latitude": primary.latitude, "longitude": primary.longitude}
        if primary is not None
        and primary.latitude is not None
        and primary.longitude is not None
        else None
    )

    description = [
        f"Confirmed hydrometric Flood incident at station {state.primary_station_id}.",
        f"Current severity level is {state.severity_level}",
    ]
    if state.return_period_years is not None:
        description[-1] += f" (Q{state.return_period_years})"
    description[-1] += f", with operational alert state {state.alert_level}."
    if change.threshold_transition:
        description.append(
            "The latest observation changed the event from "
            + change.threshold_transition.replace("_to_", " to ")
            + "."
        )
    if progression is not None:
        description.append(
            f"Observed discharge trend at station {progression.station_id} is "
            f"{progression.trend}."
        )
    if change.new_station_ids:
        description.append(
            "New hydrometric station evidence: "
            + ", ".join(str(item) for item in change.new_station_ids)
            + "."
        )
    if change.new_cell_ids:
        description.append(
            f"The observed footprint expanded into {len(change.new_cell_ids)} new cell(s)."
        )
    description.append(
        f"Operational risk is {risk.risk_score} out of 100 "
        f"({risk.risk_level}), with {risk.confidence} confidence."
    )
    if risk.primary_drivers:
        description.append(
            "Primary risk drivers: " + "; ".join(risk.primary_drivers) + "."
        )

    return EmergencyResponsePlanInput(
        hazard_type="flood",
        incident_id=validated.incident_id,
        location=location,
        event_description=" ".join(description),
        risk_context={
            "risk_semantics": risk.risk_semantics,
            "risk_score": risk.risk_score,
            "risk_level": risk.risk_level,
            "confidence": risk.confidence,
            "risk_basis": "hydrometric_severity_mapping",
            "hydrologic_severity_level": state.severity_level,
            "return_period_years": state.return_period_years,
            "alert_level": state.alert_level,
            "change_type": change.change_type,
            "threshold_transition": change.threshold_transition,
        },
        evidence_gaps=list(
            dict.fromkeys([*validated.evidence_gaps, *risk.evidence_gaps])
        ),
        limitations=list(
            dict.fromkeys([*validated.limitations, *risk.limitations])
        ),
        additional_context={
            "current_hydrologic_state": state.model_dump(mode="json"),
            "progression_assessment": (
                progression.model_dump(mode="json")
                if progression is not None
                else None
            ),
            "change_assessment": change.model_dump(mode="json"),
            "risk_assessment": risk.model_dump(mode="json"),
        },
    )


__all__ = [
    "OperationalAnalysisUnavailable",
    "build_fire_plan_input",
    "build_flood_plan_input",
]
