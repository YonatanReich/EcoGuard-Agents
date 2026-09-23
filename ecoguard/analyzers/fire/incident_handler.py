"""Detected-fire risk analysis and shared response planning."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from ecoguard.analyzers.fire.risk_analysis_agent import RiskAnalysisAgent
from ecoguard.analyzers.fire.stored_context import stored_context_for
from ecoguard.coordinator.dispatcher import (
    IncidentDispatchContext,
    IncidentProcessingResult,
)
from ecoguard.planners.shared.adapters import (
    OperationalAnalysisUnavailable,
    build_fire_plan_input,
)
from ecoguard.planners.shared.planner import EmergencyResponsePlanner


def _as_dict(value: Any) -> dict[str, Any]:
    """A value as a plain dict, whatever shape it arrived in."""
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return dict(value)


def _iso(value: object) -> str | None:
    """A time as an ISO string, or None when absent."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if value is None:
        return None
    return str(value)


def _confidence_label(raw: object, numeric: object) -> str | None:
    """A readable confidence word from whatever the provider supplied."""
    text = str(raw or "").strip().lower()
    if text in {"h", "high"}:
        return "high"
    if text in {"n", "nominal", "medium"}:
        return "nominal"
    if text in {"l", "low"}:
        return "low"
    if isinstance(numeric, (int, float)) and not isinstance(numeric, bool):
        if numeric >= 0.8:
            return "high"
        if numeric >= 0.5:
            return "nominal"
        return "low"
    return None


def detected_event_from_incident(incident: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt stored detector signals to the established DetectedFireEvent shape."""

    if "fire" not in set(incident.get("hazards") or ()):
        raise ValueError("fire_incident_required")
    latitude = incident.get("latitude")
    longitude = incident.get("longitude")
    if latitude is None or longitude is None:
        raise ValueError("fire_incident_location_missing")

    signals = [
        dict(item)
        for item in incident.get("signals") or ()
        if isinstance(item, Mapping) and item.get("hazard") == "fire"
    ]
    if not signals:
        raise ValueError("fire_incident_evidence_missing")

    satellite_signals = [
        signal
        for signal in signals
        if str(signal.get("source") or "").lower() == "firms"
        or (signal.get("evidence") or {}).get("pixels")
    ]
    satellite_signals.sort(key=lambda item: str(item.get("observed_at") or ""))
    satellite = satellite_signals[-1] if satellite_signals else None
    satellite_evidence = satellite.get("evidence") or {} if satellite else {}
    hotspots = [
        dict(item)
        for item in satellite_evidence.get("pixels") or ()
        if isinstance(item, Mapping)
    ]

    selected_hotspot: dict[str, Any] | None = None
    detection_confidence = None
    if satellite is not None:
        if hotspots:
            selected_hotspot = max(
                hotspots,
                key=lambda item: float(item.get("frp") or 0.0),
            )
        else:
            selected_hotspot = {
                "latitude": latitude,
                "longitude": longitude,
                "frp": satellite.get("value"),
            }
        selected_hotspot.setdefault("latitude", latitude)
        selected_hotspot.setdefault("longitude", longitude)
        observed_at = _iso(satellite.get("observed_at"))
        if observed_at:
            selected_hotspot.setdefault("acquisition_date", observed_at[:10])
            selected_hotspot.setdefault("acquisition_time", observed_at[11:19])
        satellites = list(satellite_evidence.get("satellites") or ())
        if satellites:
            selected_hotspot.setdefault("satellite", str(satellites[0]))
        detection_confidence = _confidence_label(
            selected_hotspot.get("normalized_confidence")
            or selected_hotspot.get("confidence"),
            satellite.get("confidence"),
        )
        selected_hotspot["normalized_confidence"] = detection_confidence

    report_signals = [
        signal
        for signal in signals
        if isinstance((signal.get("evidence") or {}).get("text_report"), Mapping)
    ]
    report_evidence = None
    if report_signals:
        observed = sorted(str(item.get("observed_at") or "") for item in report_signals)
        report_evidence = {
            "source": "Coordinator text reports",
            "reports_count": len(report_signals),
            "channels": sorted({str(item.get("source")) for item in report_signals}),
            "first_report_at": observed[0],
            "latest_report_at": observed[-1],
            "candidate_confidence": max(
                float(item.get("confidence") or 0.0) for item in report_signals
            ),
            "location_precision": incident.get("precision_m"),
            "corroborated_by_satellite": satellite is not None,
        }

    timestamp = _iso(incident.get("last_signal_at") or incident.get("first_seen_at"))
    stored = stored_context_for(incident)
    return {
        "metadata": {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "collection_status": "success",
        },
        "event_type": "fire",
        "detected": True,
        "location": {
            "latitude": float(latitude),
            "longitude": float(longitude),
        },
        "detection_confidence": detection_confidence,
        "fire_weather_severity": (stored.get("fire_danger") or {}).get("danger_class"),
        "satellite_evidence": {
            "source": "NASA FIRMS",
            "collection_status": "success" if satellite is not None else "not_available",
            "hotspots_count": (
                int(satellite_evidence.get("hotspot_count") or len(hotspots))
                if satellite is not None
                else 0
            ),
            "selected_hotspot": selected_hotspot,
            "hotspots": hotspots,
        },
        "report_evidence": report_evidence,
        # Read from what the collectors already stored rather than left empty.
        # The request-scoped fire query fetched these from three providers while
        # an operator waited; an incident has no such request, and leaving them
        # absent made the assessment report a coordinate's fire danger as
        # unknown while its band sat in the database.
        **stored,
        "source_status": {
            "coordinator": "success",
            "nasa_firms": "success" if satellite is not None else "not_available",
            "stored_context": (
                "success" if stored.get("geospatial_context") else "not_available"
            ),
        },
    }


class FireIncidentHandler:
    """Assess an existing fire, plan through the shared emergency planner."""

    name = "fire_operational_risk_planning"

    def __init__(
        self,
        *,
        risk_analyzer: object | None = None,
        planner: object | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """Build the handler with its risk analyzer and planner."""
        self._risk_analyzer = risk_analyzer or RiskAnalysisAgent()
        self._planner = planner or EmergencyResponsePlanner()
        self._clock = clock

    def _now(self) -> datetime:
        """The current time, from the injected clock."""
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Fire handler clock must carry a UTC offset")
        return value.astimezone(timezone.utc)

    def process(
        self,
        incident: Mapping[str, Any],
        context: IncidentDispatchContext,
    ) -> IncidentProcessingResult:
        """Assess one fire and plan a response.

        The only analyzer that uses a model: it produces a risk score and a written
        explanation, both grounded in the protocol corpus and rejected if they
        cannot be traced back to it.
        """
        if context.hazard != "fire" or context.route != "emergency":
            raise ValueError("Fire handler requires the emergency route")

        try:
            detected_event = detected_event_from_incident(incident)
        except Exception as error:
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="failed",
                requested_at=context.requested_at,
                completed_at=self._now(),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                analysis_status="failed",
                failure_stage="adaptation",
                failure_reason=type(error).__name__,
                requires_resource_allocation=False,
            )

        try:
            risk = _as_dict(self._risk_analyzer.analyze_event(detected_event))
        except Exception as error:
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="partial",
                requested_at=context.requested_at,
                completed_at=self._now(),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                analysis_status="success",
                risk_status="failed",
                analysis_result=detected_event,
                failure_stage="risk_analysis",
                failure_reason=type(error).__name__,
                planner_status="skipped",
                requires_resource_allocation=False,
            )

        risk_metadata = risk.get("metadata") or {}
        risk_status = str(risk_metadata.get("analysis_status") or "failed")
        if risk_status != "success":
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="partial",
                requested_at=context.requested_at,
                completed_at=self._now(),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                analysis_status="success",
                risk_status=risk_status,
                planner_status="skipped",
                analysis_result=detected_event,
                risk_assessment=risk,
                failure_stage="risk_analysis",
                failure_reason=str(
                    risk.get("error")
                    or risk_metadata.get("reason")
                    or "fire_risk_analysis_unavailable"
                ),
                requires_resource_allocation=False,
            )

        try:
            plan_input = build_fire_plan_input(detected_event, risk).model_copy(
                update={"incident_id": context.incident_id}
            )
            plan = self._planner.plan_response(plan_input)
            planner_result = _as_dict(plan)
        except OperationalAnalysisUnavailable as error:
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="partial",
                requested_at=context.requested_at,
                completed_at=self._now(),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                analysis_status="success",
                risk_status="success",
                planner_status="skipped",
                analysis_result=detected_event,
                risk_assessment=risk,
                failure_stage="planning_input",
                failure_reason=str(error),
                requires_resource_allocation=False,
            )
        except Exception as error:
            return IncidentProcessingResult(
                incident_id=context.incident_id,
                hazard=context.hazard,
                route=context.route,
                status="partial",
                requested_at=context.requested_at,
                completed_at=self._now(),
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                handler=self.name,
                analysis_status="success",
                risk_status="success",
                planner_status="failed",
                analysis_result=detected_event,
                risk_assessment=risk,
                failure_stage="planning",
                failure_reason=type(error).__name__,
                requires_resource_allocation=False,
            )

        metadata = planner_result.get("metadata") or {}
        planner_status = str(metadata.get("planning_status") or "failed")
        planner_succeeded = planner_status == "success"
        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            route=context.route,
            status="success" if planner_succeeded else "partial",
            requested_at=context.requested_at,
            completed_at=self._now(),
            analysis_id=context.analysis_id,
            coordinator_routing_id=context.coordinator_routing_id,
            handler=self.name,
            analysis_status="success",
            risk_status="success",
            planner_status=planner_status,
            analysis_result=detected_event,
            risk_assessment=risk,
            planner_result=planner_result,
            failure_stage=None if planner_succeeded else "planning",
            failure_reason=(
                None
                if planner_succeeded
                else str(
                    planner_result.get("error")
                    or metadata.get("reason")
                    or "fire_planning_failed"
                )
            ),
            requires_resource_allocation=planner_succeeded,
        )


@lru_cache(maxsize=1)
def configured_fire_incident_handler() -> FireIncidentHandler:
    """Build the production Fire risk/planning stack once per process."""

    return FireIncidentHandler()


__all__ = [
    "FireIncidentHandler",
    "configured_fire_incident_handler",
    "detected_event_from_incident",
]
