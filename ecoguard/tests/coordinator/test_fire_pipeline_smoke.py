"""Offline smoke coverage for Fire on the shared incident pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

from ecoguard.analyzers.fire.incident_handler import FireIncidentHandler
from ecoguard.api.events import shared_event_feed
from ecoguard.coordinator.dispatcher import (
    IncidentDispatchContext,
    default_handler_registry,
    dispatch_incidents,
)
from ecoguard.coordinator.event_projection import project_processing_results
from ecoguard.resource_allocator.allocation_agent import ResourceAllocationAgent
from ecoguard.planners.shared.schemas import EmergencyResponsePlan


NOW = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
CITATION = {
    "chunk_id": "offline-fire-protocol#1",
    "document_id": "offline-fire-protocol",
    "document_title": "Offline fire response protocol",
    "source_url": None,
    "heading_path": "Initial response",
    "quoted_text": "Dispatch the responsible fire team immediately.",
    "supports": "Immediate fire-service response.",
    "verified": True,
}


def _incident():
    return {
        "id": "INC-FIRE-SMOKE",
        "status": "open",
        "primary_hazard": "fire",
        "hazards": ["fire"],
        "queues": ["emergency"],
        "cells": ["cell-1"],
        "latitude": 32.73,
        "longitude": 35.03,
        "precision_m": 375.0,
        "first_seen_at": NOW,
        "last_signal_at": NOW,
        "signals": [
            {
                "cell_id": "cell-1",
                "observed_at": NOW.isoformat(),
                "hazard": "fire",
                "variable": "frp",
                "value": 64.0,
                "unit": "MW",
                "source": "firms",
                "rarity": 0.9999,
                "direction": "high",
                "confidence": 0.9,
                "evidence": {
                    "hotspot_count": 1,
                    "satellites": ["N20"],
                    "pixels": [
                        {
                            "latitude": 32.73,
                            "longitude": 35.03,
                            "frp": 64.0,
                            "confidence": "h",
                            "acquisition_date": "2026-09-22",
                            "acquisition_time": "09:00:00",
                            "satellite": "N20",
                        }
                    ],
                },
            }
        ],
    }


def _risk(detected_event):
    return {
        "metadata": {
            "timestamp": NOW.isoformat(),
            "agent": "offline_risk_analysis_agent",
            "analysis_status": "success",
            "model": None,
            "reason": None,
        },
        "event_id": "offline-event-id",
        "event_type": "fire",
        "location": dict(detected_event["location"]),
        "risk_score": 68,
        "risk_level": "high",
        "risk_semantics": "detected_event_operational_risk",
        "confidence": "medium",
        "situational_context": {"area_type": "unknown"},
        "primary_drivers": ["High-confidence 64 MW FIRMS hotspot."],
        "explanation": "A high-confidence active fire requires an operational response.",
        "evidence_gaps": ["Current weather and exposure context are unavailable."],
        "web_findings": [],
        "grounding": {
            "retriever": "bm25",
            "retrieved_chunk_ids": [CITATION["chunk_id"]],
            "citations": [dict(CITATION)],
            "unverified_citation_count": 0,
        },
        "error": None,
    }


def _plan(plan_input):
    return EmergencyResponsePlan.model_validate({
        "metadata": {
            "timestamp": NOW.isoformat(),
            "agent": "offline_emergency_response_planner",
            "planning_status": "success",
            "model": None,
            "reason": None,
        },
        "incident_id": plan_input.incident_id,
        "hazard_type": "fire",
        "location": plan_input.location.model_dump(mode="json"),
        "responding_to": plan_input.risk_context,
        "plan_summary": "Synthetic shared emergency plan for an active fire.",
        "recommended_units": ["fire_department"],
        "response_actions": [
            {
                "action": "Dispatch the responsible fire team to the incident.",
                "responsible_unit": "fire_department",
                "timeframe": "immediate",
                "supporting_protocol_chunk_ids": [CITATION["chunk_id"]],
            }
        ],
        "assumptions": ["Synthetic plan; field conditions are unconfirmed."],
        "evidence_gaps": list(plan_input.evidence_gaps),
        "limitations": list(plan_input.limitations),
        "grounding": {
            "retriever": "bm25",
            "retrieved_chunk_ids": [CITATION["chunk_id"]],
            "citations": [dict(CITATION)],
            "unverified_citation_count": 0,
            "attempts": 1,
        },
        "error": None,
    })


class _OfflineRiskAnalyzer:
    def __init__(self):
        self.calls = []

    def analyze_event(self, detected_event):
        self.calls.append(detected_event)
        return _risk(detected_event)


class _OfflineEmergencyPlanner:
    def __init__(self):
        self.calls = []

    def plan_response(self, plan_input):
        self.calls.append(plan_input)
        return _plan(plan_input)


class _FailingEmergencyPlanner:
    def plan_response(self, plan_input):
        raise RuntimeError("planner unavailable")


class _NoWriteAllocationRepository:
    def active_allocations(self):
        return []

    def claim_stations(self, **claim):
        return [
            {
                "id": 1,
                "incident_id": claim["incident_id"],
                "recommended_unit": claim["recommended_unit"],
                "station_id": candidate["database_id"],
                "allocated_at": claim["allocated_at"],
                "released_at": None,
                "distance_km": candidate["distance_km"],
                "risk_score": claim["risk_score"],
                "risk_level": claim["risk_level"],
                "allocation_policy": claim.get("allocation_policy"),
                "allocation_basis": claim.get("allocation_basis"),
                "quantity_source": claim.get("quantity_source"),
            }
            for candidate in claim["candidates"][: claim["required_count"]]
        ]


class _OfflineRoutingClient:
    provider = "mapbox"
    profile = "mapbox/driving-traffic"
    matrix_max_sources = 9

    def travel_metrics(self, stations, event_location):
        return {
            "metrics": [
                {
                    "duration_s": 300,
                    "distance_m": 4_000,
                    "origin_snapped_location": {
                        "latitude": station["latitude"],
                        "longitude": station["longitude"],
                    },
                    "origin_snap_distance_m": 0,
                }
                for station in stations
            ],
            "road_access": {
                "input_location": dict(event_location),
                "snapped_location": dict(event_location),
                "snap_distance_m": 0,
                "road_name": "Offline smoke road",
            },
        }

    def route(self, station, event_location):
        return {
            "status": "complete",
            "provider": self.provider,
            "profile": self.profile,
            "distance_m": 4_000,
            "duration_s": 300,
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [station["longitude"], station["latitude"]],
                    [event_location["longitude"], event_location["latitude"]],
                ],
            },
            "origin": None,
            "destination": {
                "input_location": dict(event_location),
                "snapped_location": dict(event_location),
                "snap_distance_m": 0,
                "road_name": "Offline smoke road",
            },
            "road_access_verified": True,
            "requires_field_access_confirmation": False,
            "offroad_segment": None,
            "steps_he": [],
        }


def _empty_catalog():
    return {"type": "FeatureCollection", "features": [], "located": 0, "total": 0}


def _fire_catalog():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [35.0, 32.7]},
                "properties": {
                    "database_id": 1,
                    "station_id": 1,
                    "name": "Test Fire Station",
                    "district": "test-district",
                },
            }
        ],
        "located": 1,
        "total": 1,
    }


def _police_catalog():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [35.01, 32.71]},
                "properties": {
                    "database_id": 2,
                    "station_id": 2,
                    "name": "Test Police Station",
                    "district": "test-district",
                    "kind": "station",
                },
            }
        ],
        "located": 1,
        "total": 1,
    }


def test_default_dispatcher_registers_fire_without_running_the_handler():
    assert ("fire", "emergency") in default_handler_registry()


def test_fire_runs_from_shared_dispatch_to_frontend_contract_without_external_calls():
    incident = _incident()
    risk_analyzer = _OfflineRiskAnalyzer()
    planner = _OfflineEmergencyPlanner()
    handler = FireIncidentHandler(
        risk_analyzer=risk_analyzer,
        planner=planner,
        clock=lambda: NOW,
    )

    results = dispatch_incidents(
        [incident], registry={("fire", "emergency"): handler}, at=NOW
    )
    assert len(results) == 1
    result = results[0]
    assert result.status == "success"
    assert result.analysis_status == "success"
    assert result.risk_status == "success"
    assert result.planner_status == "success"
    assert len(risk_analyzer.calls) == 1
    detected = risk_analyzer.calls[0]
    assert detected["event_type"] == "fire"
    assert detected["detected"] is True
    assert detected["satellite_evidence"]["selected_hotspot"]["frp"] == 64.0
    assert "spread" not in detected
    assert len(planner.calls) == 1
    assert planner.calls[0].incident_id == incident["id"]
    assert planner.calls[0].risk_context["risk_semantics"] == (
        "detected_event_operational_risk"
    )

    allocator = ResourceAllocationAgent(
        station_readers={
            "fire_department": _fire_catalog,
            "police": _empty_catalog,
            "medical_services": _empty_catalog,
        },
        routing_client=_OfflineRoutingClient(),
        allocation_repository=_NoWriteAllocationRepository(),
        town_reader=lambda **_: None,
    )
    allocator.allocate_processing_results(results)
    assert result.resource_allocation_result["requirements"]["fire_department"] == {
        "requested": 1,
        "assigned": 1,
        "shortfall": 0,
    }

    writes = []
    outcomes = project_processing_results(
        results,
        incident_reader=lambda incident_id: (
            incident if incident_id == incident["id"] else None
        ),
        projection_reader=lambda _: None,
        writer=lambda record: writes.append(record),
    )
    assert outcomes[0].status == "success"
    record = writes[0]
    assert record.event_payload["type"] == "fire"
    assert record.event_payload["details"]["risk_score"] == 68
    assert record.event_payload["details"]["spread"] is None
    assert record.event_payload["details"]["recommended_units"] == [
        "fire_department"
    ]
    assert record.event_payload["details"]["resource_allocation"]["status"] == (
        "fulfilled"
    )

    feed = shared_event_feed([
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
    ])
    assert len(feed.events) == 1
    assert feed.events[0].type == "fire"
    assert feed.events[0].id == incident["id"]


def test_fire_planning_failure_allocates_one_police_station():
    incident = _incident()
    result = dispatch_incidents(
        [incident],
        registry={
            ("fire", "emergency"): FireIncidentHandler(
                risk_analyzer=_OfflineRiskAnalyzer(),
                planner=_FailingEmergencyPlanner(),
                clock=lambda: NOW,
            )
        },
        at=NOW,
    )[0]

    assert result.status == "partial"
    assert result.planner_status == "failed"
    assert result.requires_resource_allocation is True
    assert result.fallback_allocation_context == {
        "location": {"latitude": 32.73, "longitude": 35.03},
        "risk_context": {
            "risk_semantics": "detected_event_operational_risk",
            "risk_score": 68,
            "risk_level": "high",
            "confidence": "medium",
        },
    }

    allocator = ResourceAllocationAgent(
        station_readers={
            "fire_department": _empty_catalog,
            "police": _police_catalog,
            "medical_services": _empty_catalog,
        },
        routing_client=_OfflineRoutingClient(),
        allocation_repository=_NoWriteAllocationRepository(),
        town_reader=lambda **_: None,
    )
    allocator.allocate_processing_results([result])

    allocation = result.resource_allocation_result
    assert allocation["allocation_policy"] == (
        "planning_failure_police_minimum_v1"
    )
    assert allocation["requirements"]["police"] == {
        "requested": 1,
        "assigned": 1,
        "shortfall": 0,
    }
    assert len(allocation["allocated_units"]["police_stations"]) == 1


def test_fire_risk_failure_is_reported_without_automatic_allocation():
    class FailingRiskAnalyzer:
        def analyze_event(self, _detected_event):
            raise RuntimeError("missing credentials")

    result = FireIncidentHandler(
        risk_analyzer=FailingRiskAnalyzer(),
        clock=lambda: NOW,
    ).process(
        _incident(),
        IncidentDispatchContext(
            incident_id="INC-FIRE-SMOKE",
            hazard="fire",
            route="emergency",
            analysis_id="analysis-fire-smoke",
            coordinator_routing_id="routing-fire-smoke",
            routed_by="test",
            routed_at=NOW,
            requested_at=NOW,
        ),
    )

    assert result.planner_status == "skipped"
    assert result.risk_status == "failed"
    assert result.requires_resource_allocation is False
    assert result.fallback_allocation_context is None
