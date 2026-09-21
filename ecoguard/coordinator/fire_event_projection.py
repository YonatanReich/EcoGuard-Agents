"""One fire incident, as the shape the operator's map and cards consume.

Sits beside the air-pollution mapper and follows its division of labour: the
analyser's measured findings and the planner's recommendations arrive as
separate inputs and are placed side by side in the event, neither swallowing
the other. A reader of `FireDetails` can tell which half produced any given
number, and a failure in one half leaves the other intact.

Absence is preserved on the way through. A settlement list that is empty
because nothing is exposed looks different from one that is empty because the
analyser never ran — the first has a successful `analysis_status`, the second
does not. Every field that could be mistaken for a measured zero is left None
instead.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from ecoguard.shared.events import (
    FireDetails,
    FireDetectionVerdict,
    FireDispatch,
    FireDispatchStation,
    FireEvacuationDirective,
    FireExposedSettlement,
    FireResponseAction,
    FireSharedEvent,
    FireSiteAtRisk,
    FireSpread,
    FireSpreadRing,
    ProtocolCitation,
)

logger = logging.getLogger(__name__)

# How the analyser's evacuation priorities map onto the event's vocabulary.
# The names differ because the analyser speaks about the fire and the event
# speaks to an operator, but they are one-to-one and must stay so.
PRIORITY = {"immediate": "immediate", "prepare": "prepare", "standby": "standby"}


def _ring(coordinates: Sequence[Sequence[float]] | None) -> FireSpreadRing | None:
    """A closed GeoJSON ring, or None for a fire that is not spreading."""
    if not coordinates or len(coordinates) < 4:
        return None
    return FireSpreadRing(coordinates=[[list(point) for point in coordinates]])


def _spread(analysis: Mapping[str, Any]) -> FireSpread | None:
    spread = analysis.get("spread") or {}
    if spread.get("status") != "ok":
        return None
    behaviour = analysis.get("behaviour") or {}
    return FireSpread(
        likely=_ring(spread.get("likely")),
        possible=_ring(spread.get("possible")),
        heading_deg=spread.get("heading_deg"),
        heading_compass=behaviour.get("heading_compass"),
        head_rate_m_per_min=behaviour.get("head_ros_m_per_min"),
        head_distance_m=spread.get("head_distance_m"),
        horizon_minutes=analysis.get("horizon_minutes"),
    )


def _dispatch(
    dispatch: Mapping[str, Any] | None, escalation: Mapping[str, Any] | None
) -> FireDispatch | None:
    if not dispatch or dispatch.get("status") != "ok":
        return None
    grade = dispatch.get("grade") or {}
    return FireDispatch(
        grade=grade.get("grade"),
        grade_reason=grade.get("reason"),
        teams_required=dispatch.get("teams_required"),
        teams_assigned=dispatch.get("teams_assigned"),
        teams_shortfall=dispatch.get("teams_shortfall"),
        home_district=dispatch.get("home_district"),
        stations=[
            FireDispatchStation(
                name=str(station.get("name")),
                district=station.get("district"),
                teams=station.get("teams"),
                role=str(station.get("role")),
                request_type=str(station.get("request_type")),
            )
            for station in dispatch.get("stations") or ()
        ],
        police=[dict(item) for item in dispatch.get("police_notifications") or ()],
        mda=[dict(item) for item in dispatch.get("mda_notifications") or ()],
        is_national_event=bool((escalation or {}).get("is_national")),
        national_event_basis=(escalation or {}).get("statement"),
        limits=list(dispatch.get("limits") or ()),
    )


def _title(analysis: Mapping[str, Any]) -> str:
    """Name the incident after the place it threatens, not its coordinates."""
    origin = analysis.get("origin") or {}
    if origin.get("locality"):
        return f"Fire in {origin['locality']}"
    exposure = analysis.get("exposure") or ()
    for item in exposure:
        if item.get("exposure") in {"burning", "likely"}:
            return f"Fire approaching {item['name']}"
    latitude, longitude = origin.get("latitude"), origin.get("longitude")
    if latitude is None or longitude is None:
        return "Fire detected"
    return f"Fire at {latitude:.3f}, {longitude:.3f}"


def fire_shared_event(
    analysis: Mapping[str, Any],
    planner: Mapping[str, Any] | None = None,
    *,
    incident_id: str | None = None,
) -> FireSharedEvent:
    """Build the operator-facing event from an analysis and an optional plan.

    The plan is optional on purpose. An analysed fire with no plan — because
    planning failed, or because credentials were missing — is still an event
    worth putting on a map, and withholding it until a model call succeeds
    would make the map depend on the least reliable step in the chain.
    """
    planner = planner or {}
    plan = planner.get("plan") or {}
    origin = analysis.get("origin") or {}
    totals = analysis.get("population_at_risk") or {}

    exposure = [
        FireExposedSettlement(
            name=str(item.get("name")),
            name_he=item.get("name_he"),
            population=item.get("population"),
            exposure=item.get("exposure"),
            arrival_minutes=item.get("arrival_minutes"),
            distance_m=item.get("distance_m"),
            authority_phone=item.get("authority_phone"),
            fire_district=item.get("fire_district"),
            police_station=item.get("police_station"),
        )
        for item in analysis.get("exposure") or ()
    ]

    evacuation = [
        FireEvacuationDirective(
            name=str(item.get("name")),
            priority=PRIORITY[item["priority"]],
            population=item.get("population"),
            reason=str(item.get("reason")),
            arrival_minutes=item.get("arrival_minutes"),
            authority=item.get("authority"),
            authority_phone=item.get("authority_phone"),
            police_station=item.get("police_station"),
        )
        for item in analysis.get("evacuation") or ()
        if item.get("priority") in PRIORITY
    ]

    detection = analysis.get("detection") or {}
    ring_population = analysis.get("population_in_spread") or {}

    details = FireDetails(
        risk_score=analysis.get("risk_score"),
        risk_level=analysis.get("risk_level"),
        explanation=analysis.get("headline"),
        incident_report=analysis.get("report"),
        detection=(
            FireDetectionVerdict(
                verdict=detection["verdict"],
                score=detection.get("score"),
                reasons=list(detection.get("reasons") or ()),
            )
            if detection.get("verdict") else None
        ),
        spread=_spread(analysis),
        exposed_settlements=exposure,
        sites_at_risk=[
            FireSiteAtRisk(
                name=str(site.get("name")),
                kind=str(site.get("kind")),
                category=site.get("category"),
                exposure=site.get("exposure"),
                distance_m=site.get("distance_m"),
            )
            for site in analysis.get("infrastructure_at_risk") or ()
        ],
        evacuation=evacuation,
        # None rather than 0 when the grid could not be read: an uncounted
        # population must never render as an evacuated hillside.
        people_in_spread=ring_population.get("people"),
        population_at_risk={
            key: int(value) for key, value in totals.items()
        },
        dispatch=_dispatch(planner.get("dispatch"), planner.get("escalation")),
        recommended_units=[
            item["resource_type"] for item in plan.get("resource_requests") or ()
        ],
        response_plan=[
            item["action"] for item in plan.get("immediate_actions") or ()
        ],
        response_actions=[
            FireResponseAction(
                action=item["action"],
                responsible_unit=item.get("responsible", "fire_department"),
                timeframe=(
                    item["timeframe"]
                    if item.get("timeframe") in
                    {"immediate", "within_1_hour", "within_6_hours", "ongoing"}
                    else "immediate"
                ),
            )
            for item in plan.get("immediate_actions") or ()
        ],
        protocol_citations=[
            ProtocolCitation(
                chunk_id=str(item.get("procedure_number") or ""),
                document_id=str(item.get("procedure_number") or ""),
                document_title=str(item.get("document_title") or ""),
                source_url=None,
                heading_path=str(item.get("clause_path") or ""),
                quoted_text=str(item.get("quoted_text") or ""),
                supports=str(item.get("supports") or ""),
                verified=bool(item.get("verified")),
            )
            for item in plan.get("protocol_citations") or ()
        ],
        coverage_gaps=list(plan.get("coverage_gaps") or ()),
        limits=list(analysis.get("limits") or ()),
    )

    planner_status = planner.get("status")
    return FireSharedEvent(
        id=str(incident_id or analysis.get("incident_id") or "unknown"),
        title=_title(analysis),
        description=analysis.get("headline") or "Fire detected.",
        latitude=float(origin.get("latitude") or 0.0),
        longitude=float(origin.get("longitude") or 0.0),
        observed_at=None,
        # A fire is an emergency at any size; the grade says how large, not
        # whether anyone is dispatched.
        classification="emergency",
        analysis_status="success" if analysis.get("status") == "ok" else "failed",
        planning_status=(
            "success" if planner_status == "success"
            else "failed" if planner_status == "failed"
            else "skipped"
        ),
        details=details,
    )
