"""Manual Fire scenarios through the existing pipeline, with no DB writes."""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import TypeAdapter

from ecoguard.analyzers.fire.incident_handler import FireIncidentHandler
from ecoguard.api.events import (
    manual_fire_test_enabled,
    set_manual_test_feed,
    shared_event_feed,
)
from ecoguard.api.flood_manual_test import (
    MemoryAllocationRepository,
    MemoryIncidentStore,
    RecordingAllocator,
    _jsonable,
    _show,
)
from ecoguard.coordinator.agent import coordinate
from ecoguard.coordinator.dispatcher import dispatch_touched
from ecoguard.coordinator.event_projection import project_processing_results
from ecoguard.detectors.fire.satellite import _report
from ecoguard.resource_allocator.allocation_agent import ResourceAllocationAgent
from ecoguard.resource_allocator.mapbox_client import MapboxClient
from ecoguard.planners.shared.schemas import (
    EmergencyResponsePlan,
    EmergencyResponsePlanInput,
)
from ecoguard.shared.events import SharedEvent, SharedEventFeed
from ecoguard.shared.signals import CellLocation, CellSignal


router = APIRouter(prefix="/api/dev/fire-tests", tags=["manual-fire-test"])
UTC = timezone.utc
_event_adapter = TypeAdapter(SharedEvent)
_run_lock = threading.Lock()
_latest_report: dict[str, Any] | None = None

SCENARIOS = {
    "routine_suppressed": "A persistent source with its routine signature is ignored.",
    "baseline_missing": "A hotspot with no baseline is reported instead of suppressed.",
    "persistent_novel": "A persistent source with a novel signature is reported.",
    "confirmed_fire": "Noise plus one reportable hotspot runs through the full pipeline.",
    "adjacent_deduplicated": "Two adjacent observations within two hours become one incident.",
    "separate_fires": "Two distant observations remain two independent incidents.",
    "missing_location": "A reportable signal without a dispatch location fails adaptation safely.",
    "risk_failure": "Risk analysis fails, so planning and allocation are skipped.",
    "invalid_risk_semantics": "Unsupported risk semantics are rejected by the operational planner adapter.",
    "planner_failure": "A valid risk assessment followed by a failed planner result.",
    "ended": "A full event closes only after more than six quiet hours.",
}

_CITATION = {
    "chunk_id": "synthetic-fire-manual-test#1",
    "document_id": "synthetic-fire-manual-test",
    "document_title": "Synthetic manual-test protocol",
    "source_url": None,
    "heading_path": "Initial response",
    "quoted_text": "Synthetic citation; no operational protocol claim is made.",
    "supports": "Schema-valid manual pipeline test only.",
    "verified": True,
}


def _signal(
    *,
    observed_at: datetime,
    cell_id: str = "risk-05000m-r0073-c0015",
    latitude: float | None = 32.72356612,
    longitude: float | None = 35.02752962,
    rarity: float | None = 0.9999,
    novelty: float | None = 0.7,
    frp: float = 64.0,
) -> CellSignal:
    """One synthetic fire detection, with the fields a real one would carry."""
    location = (
        CellLocation(latitude, longitude, 375.0, "frp_weighted_centroid")
        if latitude is not None and longitude is not None
        else None
    )
    signature = (
        None
        if novelty is None
        else {"score": novelty, "driver": "frp", "components": {"frp": novelty}}
    )
    return CellSignal(
        cell_id=cell_id,
        observed_at=observed_at,
        hazard="fire",
        variable="frp",
        value=frp,
        unit="MW",
        source="firms",
        rarity=rarity,
        direction="high",
        location=location,
        confidence=0.9,
        evidence={
            "hotspot_count": 2,
            "satellites": ["VIIRS_NOAA20_NRT"],
            "pixels": [
                {
                    "latitude": latitude if latitude is not None else 32.7235,
                    "longitude": longitude if longitude is not None else 35.0275,
                    "frp": 8.0,
                    "confidence": "l",
                    "acquisition_date": observed_at.date().isoformat(),
                    "acquisition_time": observed_at.strftime("%H%M"),
                    "firms_source": "VIIRS_NOAA20_NRT",
                },
                {
                    "latitude": latitude if latitude is not None else 32.7236,
                    "longitude": longitude if longitude is not None else 35.0276,
                    "frp": frp,
                    "confidence": "h",
                    "acquisition_date": observed_at.date().isoformat(),
                    "acquisition_time": observed_at.strftime("%H%M"),
                    "firms_source": "VIIRS_NOAA20_NRT",
                },
            ],
            "recent_detections": [],
            "detection_days": None if rarity is None else round((1 - rarity) * 365),
            "days_observed": None if rarity is None else 365,
            "detection_share": None if rarity is None else round(1 - rarity, 4),
            "signature": signature,
            "signature_profile": "synthetic manual-test profile",
        },
    )


def _scenario_signals(scenario: str, start: datetime) -> list[CellSignal]:
    """The detections that make up one named walkthrough."""
    routine = _signal(observed_at=start, rarity=0.90, novelty=0.20, frp=1.2)
    reportable = _signal(observed_at=start + timedelta(minutes=10))
    if scenario == "routine_suppressed":
        return [routine]
    if scenario == "baseline_missing":
        return [_signal(observed_at=start, rarity=None, novelty=None)]
    if scenario == "persistent_novel":
        return [_signal(observed_at=start, rarity=0.90, novelty=0.70)]
    if scenario == "adjacent_deduplicated":
        return [
            reportable,
            _signal(
                observed_at=start + timedelta(hours=2),
                cell_id="risk-05000m-r0074-c0015",
                latitude=32.76878471,
                longitude=35.02794975,
                frp=71.0,
            ),
        ]
    if scenario == "separate_fires":
        return [
            reportable,
            _signal(
                observed_at=start + timedelta(minutes=15),
                cell_id="risk-05000m-r0002-c0013",
                latitude=29.51304647,
                longitude=34.89677051,
                frp=43.0,
            ),
        ]
    if scenario == "missing_location":
        return [_signal(observed_at=start, latitude=None, longitude=None)]
    return [routine, reportable]


class SyntheticRiskAnalyzer:
    """Deterministic RiskAnalysisAgent replacement that cannot call Claude."""

    def __init__(self, scenario: str) -> None:
        """Build the stand-in for this walkthrough."""
        self.scenario = scenario
        self.calls: list[dict[str, Any]] = []

    def analyze_event(self, detected_event: dict[str, Any]) -> dict[str, Any]:
        """Return the analysis this walkthrough is meant to produce."""
        self.calls.append(deepcopy(detected_event))
        if self.scenario == "risk_failure":
            return {
                "metadata": {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "agent": "SyntheticFireManualTestRiskAnalyzer",
                    "analysis_status": "failed",
                    "model": None,
                    "reason": "synthetic_risk_failure",
                },
                "event_id": "synthetic-fire-event",
                "event_type": "fire",
                "location": detected_event.get("location"),
                "risk_score": None,
                "risk_level": None,
                "risk_semantics": "detected_event_operational_risk",
                "confidence": None,
                "primary_drivers": [],
                "explanation": None,
                "evidence_gaps": ["Synthetic risk failure."],
                "web_findings": [],
                "grounding": {"citations": []},
                "error": "synthetic_risk_failure",
            }
        semantics = (
            "unsupported_risk_semantics"
            if self.scenario == "invalid_risk_semantics"
            else "detected_event_operational_risk"
        )
        return {
            "metadata": {
                "timestamp": datetime.now(UTC).isoformat(),
                "agent": "SyntheticFireManualTestRiskAnalyzer",
                "analysis_status": "success",
                "model": None,
                "reason": "claude_blocked_by_manual_test_mode",
            },
            "event_id": "synthetic-fire-event",
            "event_type": "fire",
            "location": deepcopy(detected_event["location"]),
            "risk_score": 68,
            "risk_level": "high",
            "risk_semantics": semantics,
            "confidence": "medium",
            "situational_context": {"area_type": "unknown"},
            "primary_drivers": ["High-confidence 64 MW FIRMS hotspot."],
            "explanation": "A high-confidence active fire requires an operational response.",
            "assumptions": [],
            "limitations": ["Synthetic assessment; field conditions are unconfirmed."],
            "evidence_gaps": ["Current weather and exposure context are unavailable."],
            "web_findings": [],
            "grounding": {
                "retriever": "bm25",
                "retrieved_chunk_ids": [_CITATION["chunk_id"]],
                "citations": [deepcopy(_CITATION)],
                "unverified_citation_count": 0,
            },
            "error": None,
        }


class SyntheticFirePlanner:
    """Schema-valid EmergencyResponsePlanner replacement with no model call."""

    def __init__(self, scenario: str) -> None:
        """Build the stand-in for this walkthrough."""
        self.scenario = scenario
        self.calls: list[EmergencyResponsePlanInput] = []

    def plan_response(self, value: Any) -> EmergencyResponsePlan:
        """Return the plan this walkthrough is meant to produce."""
        plan_input = EmergencyResponsePlanInput.model_validate(value)
        self.calls.append(plan_input)
        if self.scenario == "planner_failure":
            return EmergencyResponsePlan.model_validate({
                "metadata": {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "agent": "SyntheticFireManualTestPlanner",
                    "planning_status": "failed",
                    "model": None,
                    "reason": "synthetic_planner_failure",
                },
                "incident_id": plan_input.incident_id,
                "hazard_type": "fire",
                "location": plan_input.location.model_dump() if plan_input.location else None,
                "error": "synthetic_planner_failure",
            })
        units = ["fire_department", "police", "medical_services"]
        actions = [
            ("Dispatch fire crews to assess and suppress the active fire.", "fire_department", "immediate"),
            ("Secure access routes and keep the public outside the hazard area.", "police", "immediate"),
            ("Stage medical support near the incident access point.", "medical_services", "within_1_hour"),
        ]
        return EmergencyResponsePlan.model_validate({
            "metadata": {
                "timestamp": datetime.now(UTC).isoformat(),
                "agent": "SyntheticFireManualTestPlanner",
                "planning_status": "success",
                "model": None,
                "reason": "claude_blocked_by_manual_test_mode",
            },
            "incident_id": plan_input.incident_id,
            "hazard_type": "fire",
            "location": plan_input.location.model_dump() if plan_input.location else None,
            "responding_to": deepcopy(plan_input.risk_context),
            "plan_summary": "Synthetic shared emergency plan for an active fire.",
            "recommended_units": units,
            "response_actions": [
                {
                    "action": action,
                    "responsible_unit": unit,
                    "timeframe": timeframe,
                    "supporting_protocol_chunk_ids": [_CITATION["chunk_id"]],
                }
                for action, unit, timeframe in actions
            ],
            "assumptions": ["Synthetic plan; field conditions have not been confirmed."],
            "evidence_gaps": list(plan_input.evidence_gaps),
            "limitations": list(plan_input.limitations),
            "grounding": {
                "retriever": "bm25",
                "retrieved_chunk_ids": [_CITATION["chunk_id"]],
                "citations": [deepcopy(_CITATION)],
                "unverified_citation_count": 0,
                "attempts": 1,
            },
            "error": None,
        })


def _require_mode() -> None:
    """Hide these routes entirely unless the walkthrough is switched on."""
    if not manual_fire_test_enabled():
        raise HTTPException(
            status_code=404,
            detail="Set ECOGUARD_MANUAL_FIRE_TEST=1 before starting the existing API",
        )


@router.get("")
def scenarios() -> dict[str, str]:
    """The walkthroughs available to run."""
    _require_mode()
    return SCENARIOS


@router.get("/latest")
def latest() -> dict[str, Any]:
    """The report from the last walkthrough that ran."""
    _require_mode()
    if _latest_report is None:
        raise HTTPException(status_code=404, detail="No manual Fire test has run")
    return _latest_report


@router.post("/{scenario}/run")
def run_scenario(scenario: str) -> dict[str, Any]:
    """Run one walkthrough end to end and report what each stage did."""
    global _latest_report
    _require_mode()
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario}")

    with _run_lock:
        try:
            start = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
            detector_input = _scenario_signals(scenario, start)
            detector_output = [signal for signal in detector_input if _report(signal)]
            report: dict[str, Any] = {
                "scenario": {"id": scenario, "description": SCENARIOS[scenario]},
                "safety": {
                    "database_writes": 0,
                    "database_reads": ["fire/police/MDA station reference data"],
                    "claude_calls": 0,
                    "telegram": "disabled",
                    "external_services": ["mapbox"],
                },
                "detector_input": detector_input,
                "detector_output": detector_output,
            }
            for key, value in report.items():
                _show(key, value)

            incidents = MemoryIncidentStore()
            coordinate_at = max(signal.observed_at for signal in detector_input) + timedelta(minutes=1)
            coordination = coordinate(detector_output, at=coordinate_at, incident_store=incidents)
            report["coordinator_output"] = coordination
            _show("coordinator_output", coordination)

            if not coordination.touched_ids:
                feed = SharedEventFeed(events=[])
                set_manual_test_feed(feed)
                report["downstream"] = {
                    "status": "skipped",
                    "reason": "detector_filtered_every_fire_signal",
                }
                report["api_events_response"] = feed
                _show("api_events_response", feed)
                _latest_report = _jsonable(report)
                return _latest_report

            risk = SyntheticRiskAnalyzer(scenario)
            planner = SyntheticFirePlanner(scenario)
            handler = FireIncidentHandler(
                risk_analyzer=risk,
                planner=planner,
                clock=lambda: coordinate_at,
            )
            processing = dispatch_touched(
                coordination.touched_ids,
                registry={("fire", "emergency"): handler},
                incident_reader=incidents.incident_by_id,
                at=coordinate_at,
            )
            report.update({
                "dispatcher_output": processing,
                "detected_event_adapter_output": [item.analysis_result for item in processing],
                "risk_analyzer_input": risk.calls,
                "risk_analyzer_output": [item.risk_assessment for item in processing],
                "response_planner_input": planner.calls,
                "response_planner_output": [item.planner_result for item in processing],
            })
            for key in (
                "dispatcher_output", "detected_event_adapter_output",
                "risk_analyzer_input", "risk_analyzer_output",
                "response_planner_input", "response_planner_output",
            ):
                _show(key, report[key])

            allocations = MemoryAllocationRepository()
            allocator = RecordingAllocator(
                routing_client=MapboxClient(),
                allocation_repository=allocations,
                incident_reader=incidents.incident_by_id,
            )
            allocation_output = allocator.allocate_processing_results(processing)
            report["resource_allocator_input"] = allocator.last_batch_input
            report["resource_allocator_output"] = allocation_output
            _show("resource_allocator_input", report["resource_allocator_input"])
            _show("resource_allocator_output", allocation_output)

            projection_records = []
            outcomes = project_processing_results(
                processing,
                incident_reader=incidents.incident_by_id,
                projection_reader=lambda _: None,
                writer=lambda record: projection_records.append(record),
            )
            active_feed = shared_event_feed([
    {
        "incident_id": record.incident_id,
        "route": record.route,
        "processing_status": record.processing_status,
        "failure_stage": record.failure_stage,
        "failure_reason": record.failure_reason,
        "retryable": record.retryable,
        "attempt_count": 1,
        "last_attempt_at": record.attempted_at,
        "processed_at": record.processed_at,
        "event_payload": record.event_payload,
        "last_successful_event_payload": record.event_payload,
    }
    for record in projection_records
    if record.event_payload is not None
])
            report["projection_output"] = {
                "outcomes": outcomes,
                "records": projection_records,
            }
            _show("projection_output", report["projection_output"])

            if scenario == "ended":
                incident = incidents.incident_by_id(coordination.touched_ids[0])
                last_signal = incident["last_signal_at"]
                exact = coordinate(
                    [], at=last_signal + timedelta(hours=6), incident_store=incidents
                )
                closed = coordinate(
                    [], at=last_signal + timedelta(hours=6, seconds=1),
                    incident_store=incidents,
                )
                released = []
                for incident_id in closed.closed:
                    released.extend(allocator.release_incident(
                        incident_id,
                        released_at=last_signal + timedelta(hours=6, seconds=1),
                        reason="incident_closed",
                    ))
                feed = SharedEventFeed(events=[])
                report["incident_lifecycle_output"] = {
                    "at_exactly_6_hours": exact,
                    "at_6_hours_1_second": closed,
                    "closed_incident": incidents.incident_by_id(incident["id"]),
                    "released_allocations": released,
                }
                _show("incident_lifecycle_output", report["incident_lifecycle_output"])
            else:
                feed = active_feed

            set_manual_test_feed(feed)
            report["api_events_response"] = feed
            _show("api_events_response", feed)
            _latest_report = _jsonable(report)
            return _latest_report
        except HTTPException:
            raise
        except Exception as error:
            _show("manual_test_failure", {
                "type": type(error).__name__, "message": str(error)
            })
            raise HTTPException(
                status_code=500,
                detail={"type": type(error).__name__, "message": str(error)},
            ) from error


__all__ = ["SCENARIOS", "router"]
