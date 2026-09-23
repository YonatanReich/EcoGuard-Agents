"""Manual Flood scenarios through the existing pipeline, with no DB writes."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, TypeAdapter
from sqlalchemy import text

from ecoguard.analyzers.flood.incident_handler import FloodRoadIncidentHandler
from ecoguard.api.events import manual_flood_test_enabled, set_manual_test_feed
from ecoguard.coordinator.agent import coordinate
from ecoguard.coordinator.dispatcher import dispatch_touched
from ecoguard.coordinator.event_projection import project_processing_results
from ecoguard.coordinator.incidents import signal_as_json
from ecoguard.database.engine import Session
from ecoguard.detectors.flood.detection_agent import FloodDetectionAgent
from ecoguard.detectors.flood.station_rules import HYDROMETRIC_SOURCE
from ecoguard.resource_allocator.allocation_agent import ResourceAllocationAgent
from ecoguard.resource_allocator.flood_road_targets import FloodRoadTargetAgent
from ecoguard.resource_allocator.mapbox_client import MapboxClient
from ecoguard.planners.shared.schemas import (
    EmergencyResponsePlan,
    EmergencyResponsePlanInput,
)
from ecoguard.shared.events import SharedEvent, SharedEventFeed
from ecoguard.shared.signals import CellSignal


router = APIRouter(prefix="/api/dev/flood-tests", tags=["manual-flood-test"])
UTC = timezone.utc
_event_adapter = TypeAdapter(SharedEvent)
_run_lock = threading.Lock()
_latest_report: dict[str, Any] | None = None

SCENARIOS = {
    "below_threshold": "Three readings below Q10; detector must ignore them.",
    "single_q10": "One Q10 reading is not enough to confirm an event.",
    "gap_over_30m": "Two Q10 readings 31 minutes apart are not consecutive.",
    "below_breaks_sequence": "A below-Q10 reading breaks the high sequence.",
    "confirmed_q10": "Noise followed by two consecutive Q10 readings.",
    "escalated_q20": "A confirmed Q10 event then escalates to Q20.",
    "ended": "A confirmed event closes after more than three quiet hours.",
}

STATION_QUERY = text(
    """
    SELECT station.source_station_id,
           coalesce(station.name_en, station.name_he) AS station_name,
           station.cell_id,
           ST_Y(station.location::geometry) AS latitude,
           ST_X(station.location::geometry) AS longitude,
           station.flow_threshold_2y_m3s,
           station.flow_threshold_5y_m3s,
           station.flow_threshold_10y_m3s,
           station.flow_threshold_20y_m3s,
           station.flow_threshold_50y_m3s,
           station.flow_threshold_100y_m3s,
           (topology.stream_context -> 'stream' ->> 'stream_id')::bigint AS stream_id
    FROM hydrometric_stations AS station
    JOIN flood_station_topology AS topology
      ON topology.hydrometric_station_id = station.id
    WHERE station.is_active IS TRUE
      AND (
        CAST(:source_station_id AS integer) IS NULL
        OR station.source_station_id = CAST(:source_station_id AS integer)
      )
      AND station.cell_id IS NOT NULL
      AND station.flow_threshold_status = 'complete_thresholds'
      AND topology.stream_context @> '{"matched": true}'::jsonb
      AND topology.stream_context -> 'stream' ->> 'stream_id' IS NOT NULL
      AND station.flow_threshold_2y_m3s > 0
      AND station.flow_threshold_2y_m3s < station.flow_threshold_5y_m3s
      AND station.flow_threshold_5y_m3s < station.flow_threshold_10y_m3s
      AND station.flow_threshold_10y_m3s < station.flow_threshold_20y_m3s
      AND station.flow_threshold_20y_m3s < station.flow_threshold_50y_m3s
      AND station.flow_threshold_50y_m3s < station.flow_threshold_100y_m3s
    ORDER BY station.source_station_id
    LIMIT 1
    """
)


def _jsonable(value: Any) -> Any:
    """A value in a form that can be printed as JSON, whatever shape it arrived in."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, CellSignal):
        return signal_as_json(value)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _show(name: str, value: Any) -> None:
    """Print one stage's output, so the walkthrough can be followed as it runs."""
    print(f"\n{'=' * 22} {name} {'=' * 22}", flush=True)
    print(json.dumps(_jsonable(value), ensure_ascii=False, indent=2), flush=True)


class ManualFloodMeasurement(BaseModel):
    observed_at: AwareDatetime
    discharge_m3s: float = Field(ge=0)


class ManualFloodRunRequest(BaseModel):
    """Optional caller-owned readings; omitted means use the named fixture."""

    source_station_id: int | None = Field(default=None, ge=1)
    measurements: list[ManualFloodMeasurement] = Field(default_factory=list)


def _station(source_station_id: int | None = None) -> dict[str, Any]:
    """A real gauge to run the walkthrough against."""
    with Session() as session:
        row = session.execute(
            STATION_QUERY, {"source_station_id": source_station_id}
        ).mappings().first()
    if row is None:
        raise RuntimeError("No eligible hydrometric station exists in the database")
    result = dict(row)
    result["thresholds_m3s"] = [
        float(result[f"flow_threshold_{years}y_m3s"])
        for years in (2, 5, 10, 20, 50, 100)
    ]
    return result


def _quarter(low: float, high: float) -> float:
    """A value a quarter of the way between two thresholds."""
    return round(low + (high - low) * 0.25, 6)


def _sample_values(scenario: str, thresholds: list[float]) -> list[tuple[int, float]]:
    """The readings that make up one named walkthrough."""
    q2, q5, q10, q20, q50, _ = thresholds
    noise = round(q2 * 0.5, 6)
    low = _quarter(q2, q5)
    monitoring = _quarter(q5, q10)
    q10_first = _quarter(q10, q20)
    q10_second = round(q10 + (q20 - q10) * 0.5, 6)
    q20_value = _quarter(q20, q50)
    return {
        "below_threshold": [(0, noise), (10, low), (20, monitoring)],
        "single_q10": [(0, noise), (10, monitoring), (20, q10_first)],
        "gap_over_30m": [(0, q10_first), (31, q10_second)],
        "below_breaks_sequence": [(0, q10_first), (10, monitoring), (20, q10_second)],
        "confirmed_q10": [(0, noise), (10, monitoring), (20, q10_first), (30, q10_second)],
        "escalated_q20": [
            (0, noise), (10, monitoring), (20, q10_first),
            (30, q10_second), (40, q20_value),
        ],
        "ended": [(0, noise), (10, monitoring), (20, q10_first), (30, q10_second)],
    }[scenario]


def _observations(
    scenario: str,
    station: Mapping[str, Any],
    start: datetime,
    measurements: list[ManualFloodMeasurement] | None = None,
) -> list[dict[str, Any]]:
    """The readings as stored observations, so the detector sees what it normally sees."""
    rows = []
    supplied = measurements or []
    sample_rows = (
        [(item.observed_at.astimezone(UTC), item.discharge_m3s) for item in supplied]
        if supplied
        else [
            (start + timedelta(minutes=minutes), discharge)
            for minutes, discharge in _sample_values(
                scenario, station["thresholds_m3s"]
            )
        ]
    )
    for identifier, (observed_at, discharge) in enumerate(sample_rows, start=1):
        station_payload = {
            "source_station_id": int(station["source_station_id"]),
            "name": station["station_name"],
            "latitude": float(station["latitude"]),
            "longitude": float(station["longitude"]),
            "discharge_m3s": discharge,
            "flow_threshold_status": "complete_thresholds",
        }
        station_payload.update({
            f"flow_threshold_{years}y_m3s": threshold
            for years, threshold in zip(
                (2, 5, 10, 20, 50, 100),
                station["thresholds_m3s"],
                strict=True,
            )
        })
        rows.append({
            "id": identifier,
            "source": HYDROMETRIC_SOURCE,
            "cell_id": station["cell_id"],
            "observed_at": observed_at,
            "ingested_at": observed_at + timedelta(minutes=1),
            "payload": {"stations": [station_payload]},
        })
    return rows


class MemoryIncidentStore:
    """The production coordinator repository contract, backed only by memory."""

    def __init__(self) -> None:
        """Build the in-memory stand-in, so the walkthrough never touches live data."""
        self.rows: dict[str, dict[str, Any]] = {}
        self.sequence = 0

    def next_incident_id(self, at: datetime) -> str:
        """The next identifier in this run."""
        self.sequence += 1
        return f"INC-TEST-{at.strftime('%Y%m%d')}-{self.sequence:04d}"

    def open_incidents(self, hazards=None) -> list[dict[str, Any]]:
        """The incidents this run has opened."""
        rows = [row for row in self.rows.values() if row["status"] == "open"]
        if hazards is not None:
            wanted = set(hazards)
            rows = [row for row in rows if wanted.intersection(row["hazards"])]
        return sorted(deepcopy(rows), key=lambda row: row["last_signal_at"], reverse=True)

    def incident_by_id(self, incident_id: str) -> dict[str, Any] | None:
        """One incident by its identifier."""
        row = self.rows.get(incident_id)
        return deepcopy(row) if row is not None else None

    def create_incident(self, incident_id: str, signal: CellSignal, queues) -> dict[str, Any]:
        """Open an incident from one detection."""
        location = signal.location
        row = {
            "id": incident_id,
            "status": "open",
            "primary_hazard": signal.hazard,
            "hazards": [signal.hazard],
            "queues": list(queues),
            "cells": [signal.cell_id],
            "latitude": location.latitude if location else None,
            "longitude": location.longitude if location else None,
            "precision_m": location.precision_m if location else None,
            "location_method": location.method if location else None,
            "first_seen_at": signal.observed_at,
            "last_signal_at": signal.observed_at,
            "closed_at": None,
            "signal_count": 1,
            "peak_rarity": signal.rarity,
            "links": [],
            "signals": [signal_as_json(signal)],
        }
        self.rows[incident_id] = row
        return deepcopy(row)

    def attach_signal(self, incident_id: str, signal: CellSignal) -> dict[str, Any]:
        """Add another detection to an incident already open."""
        row = self.rows[incident_id]
        if signal.cell_id not in row["cells"]:
            row["cells"].append(signal.cell_id)
        row["last_signal_at"] = max(row["last_signal_at"], signal.observed_at)
        row["signal_count"] += 1
        row["signals"].append(signal_as_json(signal))
        location = signal.location
        if location and (
            row["precision_m"] is None or location.precision_m < row["precision_m"]
        ):
            row.update({
                "latitude": location.latitude,
                "longitude": location.longitude,
                "precision_m": location.precision_m,
                "location_method": location.method,
            })
        return deepcopy(row)

    def merge_incidents(self, cause_id: str, effect_id: str, link: dict[str, Any]):
        """Refused: a flood-only walkthrough cannot produce a mixed-hazard incident."""
        raise AssertionError("Flood-only manual tests cannot create causal hybrids")

    def close_quiet(self, at: datetime, period_for) -> list[str]:
        """Close the incidents that have gone quiet for long enough."""
        closed = []
        for row in self.rows.values():
            if row["status"] != "open":
                continue
            if at - row["last_signal_at"] > period_for(row["primary_hazard"]):
                row["status"] = "closed"
                row["closed_at"] = at
                closed.append(row["id"])
        return closed


class MemoryAllocationRepository:
    def __init__(self) -> None:
        """Build the in-memory store, so the walkthrough never touches live allocations."""
        self.rows: list[dict[str, Any]] = []
        self.next_id = 1

    def active_allocations(self):
        """The stations currently held."""
        return deepcopy([row for row in self.rows if row["released_at"] is None])

    def claim_stations(self, **claim):
        """Hold stations against an incident."""
        active = [
            row for row in self.rows
            if row["incident_id"] == claim["incident_id"]
            and row["recommended_unit"] == claim["recommended_unit"]
            and row["released_at"] is None
        ]
        used = {row["station_id"] for row in active}
        for candidate in claim["candidates"]:
            if len(active) >= claim["required_count"]:
                break
            if candidate["database_id"] in used:
                continue
            row = {
                "id": self.next_id,
                "incident_id": claim["incident_id"],
                "recommended_unit": claim["recommended_unit"],
                "station_id": candidate["database_id"],
                "allocated_at": claim["allocated_at"],
                "released_at": None,
                "release_reason": None,
                "distance_km": candidate["distance_km"],
                "risk_score": claim["risk_score"],
                "risk_level": claim["risk_level"],
                "allocation_policy": claim.get("allocation_policy"),
                "allocation_basis": claim.get("allocation_basis"),
                "quantity_source": claim.get("quantity_source"),
            }
            self.next_id += 1
            self.rows.append(row)
            active.append(row)
            used.add(row["station_id"])
        return deepcopy(active)

    def release_incident(self, incident_id, *, released_at, reason):
        """Release everything held against one incident."""
        released = []
        for row in self.rows:
            if row["incident_id"] == incident_id and row["released_at"] is None:
                row["released_at"] = released_at
                row["release_reason"] = reason
                released.append(deepcopy(row))
        return released


class SyntheticPlanner:
    """Schema-valid planner replacement that cannot call Claude."""

    def __init__(self) -> None:
        """Build the stand-in for this walkthrough."""
        self.last_input: EmergencyResponsePlanInput | None = None

    def plan_response(self, analysis) -> EmergencyResponsePlan:
        """Return the plan this walkthrough is meant to produce."""
        validated = EmergencyResponsePlanInput.model_validate(analysis)
        self.last_input = validated
        risk = validated.risk_context or {}
        chunk = "synthetic-flood-manual-test"
        return EmergencyResponsePlan.model_validate({
            "metadata": {
                "timestamp": datetime.now(UTC).isoformat(),
                "agent": "SyntheticFloodManualTestPlanner",
                "planning_status": "success",
                "model": None,
                "reason": "claude_blocked_by_manual_test_mode",
            },
            "incident_id": validated.incident_id,
            "hazard_type": "flood",
            "location": validated.location.model_dump() if validated.location else None,
            "responding_to": {
                "risk_semantics": risk.get("risk_semantics"),
                "risk_score": risk.get("risk_score"),
                "risk_level": risk.get("risk_level"),
                "risk_confidence": risk.get("confidence"),
                "severity_level": risk.get("hydrologic_severity_level"),
                "return_period_years": risk.get("return_period_years"),
                "alert_level": risk.get("alert_level"),
            },
            "plan_summary": "Synthetic response plan used only to exercise the full Flood pipeline.",
            "recommended_units": ["fire_department", "police", "medical_services"],
            "response_actions": [
                {
                    "action": "Assess flood access and prepare water rescue support at the assigned site.",
                    "responsible_unit": "fire_department", "timeframe": "immediate",
                    "supporting_protocol_chunk_ids": [chunk],
                },
                {
                    "action": "Secure unsafe approaches and prevent public entry to the affected stream area.",
                    "responsible_unit": "police", "timeframe": "immediate",
                    "supporting_protocol_chunk_ids": [chunk],
                },
                {
                    "action": "Stage medical response near the selected operational access point.",
                    "responsible_unit": "medical_services", "timeframe": "within_1_hour",
                    "supporting_protocol_chunk_ids": [chunk],
                },
            ],
            "assumptions": ["Synthetic plan; field conditions have not been confirmed."],
            "evidence_gaps": validated.evidence_gaps,
            "limitations": validated.limitations,
            "grounding": {
                "retriever": "bm25", "retrieved_chunk_ids": [chunk],
                "citations": [{
                    "chunk_id": chunk,
                    "document_title": "Synthetic manual-test protocol",
                    "quoted_text": "Synthetic citation; no operational protocol claim is made.",
                    "supports": "Schema-valid manual pipeline test only.",
                }],
                "unverified_citation_count": 0, "attempts": 1,
            },
            "error": None,
        })


class RecordingRoadTargeter:
    def __init__(self, targeter: FloodRoadTargetAgent) -> None:
        """Wrap the real road targeter, keeping its last result for the report."""
        self.targeter = targeter
        self.last_output = None

    def identify(self, incident):
        """Identify the affected roads, keeping a copy of the result for the report."""
        self.last_output = self.targeter.identify(incident)
        return deepcopy(self.last_output)


class RecordingAllocator(ResourceAllocationAgent):
    def __init__(self, **kwargs) -> None:
        """Wrap the real allocator, keeping its last input for the report."""
        self.last_batch_input = None
        super().__init__(**kwargs)

    def allocate_batch(self, requests, now=None):
        """Allocate for several requests, keeping a copy of the input for the report."""
        self.last_batch_input = deepcopy(requests)
        return super().allocate_batch(requests, now=now)


def _require_mode() -> None:
    """Hide these routes entirely unless the walkthrough is switched on."""
    if not manual_flood_test_enabled():
        raise HTTPException(
            status_code=404,
            detail="Set ECOGUARD_MANUAL_FLOOD_TEST=1 before starting the existing API",
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
        raise HTTPException(status_code=404, detail="No manual Flood test has run")
    return _latest_report


@router.post("/{scenario}/run")
def run_scenario(
    scenario: str, request: ManualFloodRunRequest | None = None
) -> dict[str, Any]:
    """Run one walkthrough end to end and report what each stage did."""
    global _latest_report
    _require_mode()
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario}")

    with _run_lock:
        try:
            start = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
            supplied = request or ManualFloodRunRequest()
            station = _station(supplied.source_station_id)
            observations = _observations(
                scenario, station, start, supplied.measurements
            )
            if len(observations) < 2:
                raise ValueError("At least two measurements are required")
            detector = FloodDetectionAgent()
            accepted = [row for row in observations if detector.accepts_pending(row)]
            signals = detector.evaluate(
                cell_id=station["cell_id"],
                observations=accepted,
                stream_ids={int(station["source_station_id"]): int(station["stream_id"])},
                target_observed_at={row["observed_at"] for row in accepted},
            )
            report = {
                "scenario": {"id": scenario, "description": SCENARIOS[scenario]},
                "safety": {
                    "database_writes": 0,
                    "database_reads": ["hydrometric/road/station reference data"],
                    "claude_calls": 0,
                    "telegram": "disabled",
                    "external_services": ["mapbox"],
                },
                "selected_station": station,
                "detector_input": observations,
                "detector_output": signals,
            }
            for key in report:
                _show(key, report[key])

            incident_store = MemoryIncidentStore()
            coordinate_at = observations[-1]["observed_at"] + timedelta(minutes=1)
            coordination = coordinate(
                signals, at=coordinate_at, incident_store=incident_store
            )
            report["coordinator_output"] = coordination
            _show("coordinator_output", coordination)

            if not coordination.touched_ids:
                feed = SharedEventFeed(events=[])
                set_manual_test_feed(feed)
                report.update({
                    "downstream": {
                        "status": "skipped",
                        "reason": "detector_emitted_no_confirmed_flood_signal",
                    },
                    "api_events_response": feed,
                })
                _show("api_events_response", feed)
                _latest_report = _jsonable(report)
                return _latest_report

            planner = SyntheticPlanner()
            handler = FloodRoadIncidentHandler(
                planner=planner, clock=lambda: coordinate_at
            )
            processing = dispatch_touched(
                coordination.touched_ids,
                registry={("flood", "emergency"): handler},
                incident_reader=incident_store.incident_by_id,
                at=coordinate_at,
            )
            report["dispatcher_output"] = processing
            report["event_analyzer_output"] = processing[0].analysis_result
            report["risk_analyzer_output"] = processing[0].risk_assessment
            report["response_planner_input"] = planner.last_input
            report["response_planner_output"] = processing[0].planner_result
            for key in (
                "dispatcher_output", "event_analyzer_output", "risk_analyzer_output",
                "response_planner_input", "response_planner_output",
            ):
                _show(key, report[key])

            allocations = MemoryAllocationRepository()
            mapbox = MapboxClient()
            targeter = RecordingRoadTargeter(
                FloodRoadTargetAgent(mapbox_client=mapbox)
            )
            allocator = RecordingAllocator(
                routing_client=mapbox,
                allocation_repository=allocations,
                flood_target_agent=targeter,
                incident_reader=incident_store.incident_by_id,
            )
            allocation_output = allocator.allocate_processing_results(processing)
            report["flood_road_targeter_output"] = targeter.last_output
            report["resource_allocator_input"] = allocator.last_batch_input
            report["resource_allocator_output"] = allocation_output
            for key in (
                "flood_road_targeter_output", "resource_allocator_input",
                "resource_allocator_output",
            ):
                _show(key, report[key])

            projection_records = []
            outcomes = project_processing_results(
                processing,
                incident_reader=incident_store.incident_by_id,
                projection_reader=lambda _: None,
                writer=lambda record: projection_records.append(record),
            )
            payloads = [record.event_payload for record in projection_records if record.event_payload]
            active_feed = SharedEventFeed(
                events=[_event_adapter.validate_python(payload) for payload in payloads]
            )
            report["projection_output"] = {
                "outcomes": outcomes,
                "records": projection_records,
            }
            _show("projection_output", report["projection_output"])

            if scenario == "ended":
                incident = incident_store.incident_by_id(coordination.touched_ids[0])
                last_signal = incident["last_signal_at"]
                exact = coordinate(
                    [], at=last_signal + timedelta(hours=3),
                    incident_store=incident_store,
                )
                closed = coordinate(
                    [], at=last_signal + timedelta(hours=3, seconds=1),
                    incident_store=incident_store,
                )
                released = []
                for incident_id in closed.closed:
                    released.extend(allocator.release_incident(
                        incident_id,
                        released_at=last_signal + timedelta(hours=3, seconds=1),
                        reason="incident_closed",
                    ))
                feed = SharedEventFeed(events=[])
                report["incident_lifecycle_output"] = {
                    "at_exactly_3_hours": exact,
                    "at_3_hours_1_second": closed,
                    "closed_incident": incident_store.incident_by_id(incident["id"]),
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
