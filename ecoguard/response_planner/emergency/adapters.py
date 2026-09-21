"""Adapters from existing analyzer outputs into the shared planning contract."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_event_id
from ecoguard.analyzers.emergency.earthquake.impact import EarthquakeImpact, LIMITATION
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


# The spread analyser's own severity scale, declared here so a reader of the
# planner input can never mistake it for the other two. `estimated_fire_risk`
# is 0-1 and is about ignition; `detected_event_operational_risk` is 0-100 and
# is about how bad an existing fire is; this is 0-100 and is about how bad its
# *spread* is about to be over a stated horizon.
FIRE_SPREAD_SEMANTICS = "fire_spread_forecast"

# EmergencyResponsePlanInput caps these, and a value over the cap fails
# validation rather than truncating. Bounded here so a fire with forty exposed
# settlements produces a shorter list instead of no plan at all.
MAX_EVIDENCE_GAPS = 16
MAX_LIMITATIONS = 24
MAX_DESCRIPTION = 6000


def build_fire_spread_plan_input(
    analysis: Mapping[str, Any],
) -> EmergencyResponsePlanInput:
    """Adapt a `spread_analyzer` result into the shared planning contract.

    Separate from `build_fire_plan_input`, which adapts the *other* fire path:
    a live point query whose evidence is a `DetectedFireEvent` and whose score
    is operational risk. That adapter rejects anything not carrying
    `detected_event_operational_risk`, and correctly so — the two scores mean
    different things and silently swapping one for the other is exactly the
    confusion the `risk_semantics` field exists to prevent.

    So this does not dress a spread forecast up as a detection. It targets
    `EmergencyResponsePlanInput` directly, which is what the shared planner
    actually consumes and which its own docstring calls analyzer-agnostic.

    Raises:
        OperationalAnalysisUnavailable: when the analysis made no assessment.
            A plan built on a forecast that did not happen is the fabrication
            the planner's hard gate exists to prevent, and a stalled fire is
            not a quiet one — it is a fire this analyser has nothing to say
            about, which is a different thing and not a basis for planning.
    """
    result = _mapping(analysis)
    if result.get("risk_semantics") != FIRE_SPREAD_SEMANTICS:
        raise OperationalAnalysisUnavailable("not_a_fire_spread_forecast")
    if result.get("status") != "ok":
        raise OperationalAnalysisUnavailable(
            f"spread_analysis_{result.get('status') or 'missing'}"
        )
    if not isinstance(result.get("risk_score"), int) or isinstance(
        result.get("risk_score"), bool
    ):
        raise OperationalAnalysisUnavailable("spread_analysis_unscored")

    origin = _mapping(result.get("origin"))
    report = result.get("report")
    if not isinstance(report, str) or not report.strip():
        raise OperationalAnalysisUnavailable("spread_analysis_has_no_report")

    # `event_description` drives BM25 retrieval, so what goes in it decides
    # which doctrine the planner gets to cite.
    #
    # The full report was the obvious thing to put here and it retrieves badly.
    # It is dense with weather and fuel vocabulary — humidity, wind, moisture,
    # danger — so on a four-document corpus it matches the Fire Weather Index
    # classification document almost every time, and the planner ends up citing
    # band definitions when it needed engagement and triage doctrine. Measured,
    # not guessed: 15 of 16 retrieved chunks across four scenarios were FWI.
    #
    # So the description is the planning view — what is burning, what it
    # threatens, who has to move — and the full narrative travels in
    # additional_context, which is serialised into the same prompt. Nothing is
    # lost to the model; only the retrieval query changes.
    description = _planning_description(result, origin)[:MAX_DESCRIPTION]

    location = None
    if origin.get("latitude") is not None and origin.get("longitude") is not None:
        location = {
            "latitude": float(origin["latitude"]),
            "longitude": float(origin["longitude"]),
        }

    evacuation = list(result.get("evacuation") or ())
    exposure = list(result.get("exposure") or ())

    try:
        return EmergencyResponsePlanInput(
            incident_id=result.get("incident_id"),
            hazard_type="fire",
            location=location,
            event_description=description,
            risk_context={
                "risk_score": result.get("risk_score"),
                "risk_level": result.get("risk_level"),
                "risk_semantics": FIRE_SPREAD_SEMANTICS,
                "horizon_minutes": result.get("horizon_minutes"),
            },
            evidence_gaps=[
                str(item) for item in (result.get("evidence_gaps") or ())
            ][:MAX_EVIDENCE_GAPS],
            limitations=[
                str(item) for item in (result.get("limits") or ())
            ][:MAX_LIMITATIONS],
            additional_context={
                "analyser": result.get("agent"),
                "assessed_at": result.get("assessed_at"),
                "origin": dict(origin),
                "fire_behaviour": dict(_mapping(result.get("behaviour"))),
                "population_at_risk": dict(_mapping(result.get("population_at_risk"))),
                "population_in_spread": (
                    dict(_mapping(result.get("population_in_spread")))
                    if result.get("population_in_spread") else None
                ),
                # Trimmed of geometry. The planner decides unit types and
                # actions; it does not draw maps, and 72 vertices per ring
                # through a context window buys nothing.
                # Whether this is a fire at all, and on what evidence. The
                # planner has to know it is planning against a doubtful
                # detection; a full response to a hot factory roof is the
                # expensive half of this system's failure modes.
                "detection": dict(_mapping(result.get("detection"))),
                "infrastructure_at_risk": [
                    {
                        key: item.get(key) for key in (
                            "name", "kind", "category", "exposure", "distance_m",
                        )
                    }
                    for item in result.get("infrastructure_at_risk") or ()
                ],
                "infrastructure_summary": dict(
                    _mapping(result.get("infrastructure_summary"))
                ),
                "fire_history": (
                    dict(_mapping(result.get("fire_history")))
                    if result.get("fire_history") else None
                ),
                "settlements_exposed": [
                    {
                        key: item.get(key) for key in (
                            "name", "name_he", "population", "exposure",
                            "arrival_minutes", "distance_m", "authority_phone",
                            "fire_district", "police_station",
                        )
                    }
                    for item in exposure
                ],
                "evacuation_priority": evacuation,
                "headline": result.get("headline"),
            },
        )
    except (TypeError, ValueError) as error:
        raise OperationalAnalysisUnavailable("spread_analysis_unadaptable") from error


def _planning_description(
    result: Mapping[str, Any], origin: Mapping[str, Any]
) -> str:
    """The incident stated as a planning problem rather than as a forecast.

    Deliberately in the vocabulary of response — evacuation, structures
    threatened, access, life safety — because that is what has to match the
    doctrine an action plan cites. The meteorology that produced these numbers
    is in the full report and in `fire_behaviour`; repeating it here only
    competes with the operative facts for retrieval weight.
    """
    behaviour = _mapping(result.get("behaviour"))
    totals = _mapping(result.get("population_at_risk"))
    exposure = list(result.get("exposure") or ())
    evacuation = list(result.get("evacuation") or ())
    where = origin.get("locality") or "open ground"

    parts = [
        f"Wildfire incident at {where}, spreading "
        f"{behaviour.get('heading_compass') or 'unknown direction'} at "
        f"{behaviour.get('head_ros_m_per_min')} metres per minute through "
        f"{str(behaviour.get('dominant_fuel') or 'mixed fuel').replace('_', ' ')}.",
        f"Spread severity {result.get('risk_level')} "
        f"({result.get('risk_score')} of 100) over the next "
        f"{result.get('horizon_minutes')} minutes.",
    ]

    burning = [item for item in exposure if item.get("exposure") == "burning"]
    if burning:
        parts.append(
            "Fire is inside the built-up area of "
            + ", ".join(str(item.get("name")) for item in burning)
            + ". Structures are threatened and life safety is the first problem."
        )

    immediate = [item for item in evacuation if item.get("priority") == "immediate"]
    prepare = [item for item in evacuation if item.get("priority") == "prepare"]
    if immediate:
        parts.append(
            "Evacuation required immediately for "
            + ", ".join(str(item.get("name")) for item in immediate)
            + "."
        )
    if prepare:
        parts.append(
            "Evacuation preparation for "
            + ", ".join(str(item.get("name")) for item in prepare)
            + "."
        )

    population = _mapping(result.get("population_in_spread")).get("people")
    if population is not None:
        parts.append(f"{population:,} residents inside the forecast fire perimeter.")
    if totals.get("likely"):
        parts.append(
            f"{totals['likely']:,} residents in settlements on the forecast path."
        )

    summary = _mapping(result.get("infrastructure_summary"))
    counts = _mapping(summary.get("counts"))
    if counts.get("hazard"):
        hazards = [
            str(item.get("kind"))
            for item in result.get("infrastructure_at_risk") or ()
            if item.get("category") == "hazard"
        ]
        parts.append(
            "Hazardous sites in the path: "
            + ", ".join(dict.fromkeys(hazards))
            + ". Exclusion and hazardous-material considerations apply."
        )
    if counts.get("life_safety"):
        sites = [
            str(item.get("kind"))
            for item in result.get("infrastructure_at_risk") or ()
            if item.get("category") == "life_safety"
        ]
        parts.append(
            "Sites whose occupants cannot self-evacuate in the path: "
            + ", ".join(dict.fromkeys(sites))
            + ". Assisted evacuation and transport required."
        )

    detection = _mapping(result.get("detection"))
    if detection.get("verdict") in {"possible", "doubtful"}:
        parts.append(
            f"Detection is only {detection['verdict']} "
            f"({detection.get('score')} of 100) — confirm on scene before "
            "committing a full response."
        )

    parts.append(
        "Requires decisions on unit types to commit, evacuation, road closures, "
        "structure protection and crew safety at the fireline."
    )
    return " ".join(parts)

def build_earthquake_plan_input(
    impact: EarthquakeImpact,
    *,
    incident_id: str,
) -> EmergencyResponsePlanInput:
    """Adapt deterministic Earthquake impact facts without adding risk claims."""

    towns = [town.model_dump(mode="json") for town in impact.towns.towns]
    town_status = impact.towns.status.value
    population = dict(impact.population_summary)
    description_parts = [
        f"GSI reported earthquake {impact.provider_event_id} at "
        f"{impact.observed_at.isoformat()} with magnitude {impact.magnitude} and "
        f"depth {impact.depth_km} km.",
        f"The epicenter is at latitude {impact.latitude}, longitude {impact.longitude}.",
        f"The deterministic Estimated Impact Area screening radius is {impact.radius_km} km.",
        f"Town intersection status is {town_status}; {len(towns)} intersecting town records are available.",
        (
            "Population intersection status is "
            f"{population.get('status')}; estimated population is "
            f"{population.get('estimated_population')} across "
            f"{population.get('intersected_cell_count')} intersected grid cells."
        ),
        LIMITATION,
    ]
    evidence_gaps = []
    if not town_status.startswith("SUCCESS"):
        evidence_gaps.append(
            impact.towns.reason or "Town intersection data is unavailable."
        )
    if population.get("status") != "available":
        evidence_gaps.append(
            str(population.get("reason") or "Population intersection data is unavailable.")
        )

    return EmergencyResponsePlanInput(
        incident_id=incident_id,
        hazard_type="earthquake",
        location={"latitude": impact.latitude, "longitude": impact.longitude},
        event_description=" ".join(description_parts),
        risk_context=None,
        evidence_gaps=evidence_gaps,
        limitations=[LIMITATION],
        additional_context={
            "provider_event_id": impact.provider_event_id,
            "observed_at": impact.observed_at.isoformat(),
            "magnitude": impact.magnitude,
            "depth_km": impact.depth_km,
            "estimated_impact_radius_km": impact.radius_km,
            "estimated_impact_area": impact.area,
            "town_intersection": {
                "status": town_status,
                "source": impact.towns.source,
                "reason": impact.towns.reason,
                "towns": towns,
            },
            "population_summary": population,
            "provider": impact.provider,
            "source": impact.source,
        },
    )
