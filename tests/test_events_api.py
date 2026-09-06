"""
Tests for the events API.

Covers the health check and the /api/detected-events contract: that the endpoint
responds, reports per-service status, and flattens the three agent results into
the shape the dashboard consumes.

Nothing here touches the network. The endpoint resolves its agents from module
globals at call time, so a fixture swaps them for mocks and restores them
afterwards. That deliberately avoids introducing FastAPI's Depends —
`backend.main` uses it nowhere, and adding dependency injection to it would be a
larger change than the one this test needs.

Two of the original assertions had to change once the endpoint stopped serving
mock data:

- "events is non-empty" is no longer true. A real scan usually detects nothing,
  and an empty list is the correct answer, so that is now two tests: one for a
  detection and one for a clean scan.
- "risk_score is between 0 and 100" only holds when the analysis succeeded.
  Skipped and failed analyses report None, because absence of a score is not a
  score of zero.

Run with: pytest
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Put the repository root on sys.path so "backend.main" resolves when pytest
# is invoked from anywhere, not just the project root.
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from backend import main
from backend.main import app

# TestClient calls the app in-process — no running uvicorn server needed.
client = TestClient(app)


DETECTED_EVENT = {
    "metadata": {"timestamp": "2026-08-27T09:00:00Z", "collection_status": "success"},
    "event_type": "fire",
    "detected": True,
    "location": {"latitude": 31.9, "longitude": 34.8},
    "detection_confidence": "high",
    "fire_weather_severity": "very_high",
    "satellite_evidence": {
        "source": "NASA FIRMS",
        "hotspots_count": 2,
        "selected_hotspot": {
            "latitude": 31.9,
            "longitude": 34.8,
            "acquisition_date": "2026-08-27",
            "acquisition_time": "0132",
            "frp": 74.2,
        },
        "hotspots": [],
    },
    "fire_danger": {"danger_level": "very_high", "fwi_min": 38.0, "fwi_max": 50.0},
    "weather_context": {"current": {"wind_speed_kmh": 30.0}, "forecast": {"daily": {}}},
    "geospatial_context": {"nearby_settlements": [{"name": "Givat Shmuel"}]},
}

NO_EVENT = {
    "metadata": {"timestamp": "2026-08-27T09:00:00Z", "collection_status": "success"},
    "event_type": "fire",
    "detected": False,
    "location": {"latitude": 31.9, "longitude": 34.8},
    "detection_confidence": None,
    "fire_weather_severity": None,
    "satellite_evidence": {"source": "NASA FIRMS", "hotspots_count": 0, "selected_hotspot": None},
    "fire_danger": None,
    "weather_context": None,
    "geospatial_context": None,
}

FAILED_DETECTION = {
    "metadata": {"timestamp": "2026-08-27T09:00:00Z", "collection_status": "failed"},
    "event_type": "fire",
    "detected": None,
    "location": {"latitude": 31.9, "longitude": 34.8},
    "satellite_evidence": {
        "source": "NASA FIRMS",
        "collection_status": "failed",
        "error": "timeout",
    },
    "fire_danger": None,
    "weather_context": None,
    "geospatial_context": None,
}

SUCCESSFUL_RISK = {
    "metadata": {
        "timestamp": "2026-08-27T09:00:00Z",
        "agent": "RiskAnalysisAgent",
        "analysis_status": "success",
        "model": "claude-sonnet-5",
        "reason": None,
    },
    "event_type": "fire",
    "location": {"latitude": 31.9, "longitude": 34.8},
    "risk_score": 78,
    "risk_level": "high",
    "confidence": "medium",
    "primary_drivers": ["very high FWI class"],
    "explanation": "Very high fire danger with wind supporting spread.",
    "evidence_gaps": [],
    "grounding": {
        "retriever": "bm25",
        "retrieved_chunk_ids": ["doc#section#0"],
        "citations": [{"chunk_id": "doc#section#0", "verified": True}],
        "unverified_citation_count": 0,
    },
    "error": None,
}

SKIPPED_RISK = {
    "metadata": {
        "timestamp": "2026-08-27T09:00:00Z",
        "agent": "RiskAnalysisAgent",
        "analysis_status": "skipped",
        "model": None,
        "reason": "no_event",
    },
    "risk_score": None,
    "risk_level": None,
    "confidence": None,
    "primary_drivers": [],
    "explanation": None,
    "evidence_gaps": [],
    "grounding": {"citations": []},
    "error": None,
}

SUCCESSFUL_PLAN = {
    "metadata": {
        "timestamp": "2026-08-27T09:00:00Z",
        "agent": "ResponsePlanningAgent",
        "planning_status": "success",
        "model": "claude-sonnet-5",
        "reason": None,
    },
    "recommended_units": ["fire_department", "police"],
    "response_actions": [
        {
            "action": "Establish incident command and confirm escape routes.",
            "responsible_unit": "fire_department",
            "timeframe": "immediate",
        },
    ],
    "plan_summary": "Protect Givat Shmuel and contain the eastern flank.",
    "assumptions": [],
    "grounding": {"citations": [{"chunk_id": "doc#action#0", "verified": True}]},
    "error": None,
}

SKIPPED_PLAN = {
    "metadata": {
        "timestamp": "2026-08-27T09:00:00Z",
        "agent": "ResponsePlanningAgent",
        "planning_status": "skipped",
        "model": None,
        "reason": "risk_analysis_unavailable",
    },
    "recommended_units": [],
    "response_actions": [],
    "plan_summary": None,
    "assumptions": [],
    "grounding": {"citations": []},
    "error": None,
}


@pytest.fixture()
def pipeline():
    """
    Replace the three pipeline agents with mocks for the duration of a test.

    Defaults to the happy path: one detected event, assessed and planned.
    Restores the real agents afterwards so tests stay independent.
    """
    originals = (main.fire_detection_agent, main.risk_agent, main.planning_agent)

    main.fire_detection_agent = MagicMock()
    main.risk_agent = MagicMock()
    main.planning_agent = MagicMock()

    main.fire_detection_agent.detect_fire.return_value = DETECTED_EVENT
    main.risk_agent.analyze_event.return_value = SUCCESSFUL_RISK
    main.planning_agent.plan_response.return_value = SUCCESSFUL_PLAN

    yield main.fire_detection_agent, main.risk_agent, main.planning_agent

    main.fire_detection_agent, main.risk_agent, main.planning_agent = originals


# --------------------------------------------------------------------------
# Health check
# --------------------------------------------------------------------------


def test_root_endpoint_returns_status_200():
    """The health check responds 200 and reports success."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "success"


# --------------------------------------------------------------------------
# Detected events
# --------------------------------------------------------------------------


def test_detected_events_endpoint_returns_status_200(pipeline):
    """The events endpoint is reachable and does not error."""
    response = client.get("/api/detected-events")

    assert response.status_code == 200


def test_detected_events_response_contains_events_list(pipeline):
    """
    The response wraps events in an "events" list.

    The dashboard maps over this directly, so both the key and the list type are
    part of the contract. Note it no longer asserts the list is non-empty —
    see the module docstring.
    """
    response = client.get("/api/detected-events")
    data = response.json()

    assert "events" in data
    assert isinstance(data["events"], list)


def test_a_detection_produces_exactly_one_event(pipeline):
    response = client.get("/api/detected-events")

    assert len(response.json()["events"]) == 1


def test_a_clean_scan_produces_no_events(pipeline):
    """
    detected is False means the scan ran and found nothing.

    An empty list is the correct answer; inventing an event would misreport it.
    """
    detection, risk, plan = pipeline
    detection.detect_fire.return_value = NO_EVENT
    risk.analyze_event.return_value = SKIPPED_RISK
    plan.plan_response.return_value = SKIPPED_PLAN

    response = client.get("/api/detected-events")
    data = response.json()

    assert response.status_code == 200
    assert data["events"] == []
    assert data["metadata"]["collection_status"] == "success"


def test_detected_event_contains_latitude_and_longitude(pipeline):
    """Every event is placeable on the map."""
    response = client.get("/api/detected-events")
    event = response.json()["events"][0]

    assert "latitude" in event
    assert "longitude" in event
    assert event["latitude"] == 31.9


def test_detected_event_risk_score_is_between_0_and_100(pipeline):
    """
    Risk scores stay inside the documented band when the analysis succeeded.

    When it did not, the score is None — a skipped analysis is not a score of
    zero, and reporting one would tell an operator the area is safe.
    """
    response = client.get("/api/detected-events")
    event = response.json()["events"][0]

    if event["analysis_status"] == "success":
        assert 0 <= event["risk_score"] <= 100
    else:
        assert event["risk_score"] is None


def test_failed_detection_returns_200_with_no_events(pipeline):
    """
    A satellite outage is reported in metadata, not as a 502.

    The dashboard fetches this on page load and only console-logs failures, so a
    502 would blank the map with no explanation for the user.
    """
    detection, risk, plan = pipeline
    detection.detect_fire.return_value = FAILED_DETECTION
    risk.analyze_event.return_value = SKIPPED_RISK
    plan.plan_response.return_value = SKIPPED_PLAN

    response = client.get("/api/detected-events")
    data = response.json()

    assert response.status_code == 200
    assert data["events"] == []
    assert data["metadata"]["collection_status"] == "failed"
    assert data["metadata"]["services"]["detection"]["status"] == "failed"


def test_event_flattens_the_plan_for_the_dashboard(pipeline):
    """response_plan is the flattened form; response_actions keeps the detail."""
    response = client.get("/api/detected-events")
    event = response.json()["events"][0]

    assert event["response_plan"] == [
        "Establish incident command and confirm escape routes."
    ]
    assert event["response_actions"][0]["responsible_unit"] == "fire_department"
    assert event["recommended_units"] == ["fire_department", "police"]


def test_event_merges_citations_from_both_reasoning_steps(pipeline):
    """Grounding evidence from the risk call and the planning call both surface."""
    response = client.get("/api/detected-events")
    event = response.json()["events"][0]

    chunk_ids = [c["chunk_id"] for c in event["protocol_citations"]]

    assert "doc#section#0" in chunk_ids
    assert "doc#action#0" in chunk_ids


def test_event_id_is_a_stable_string(pipeline):
    """
    The id is a hash of the hotspot, not a counter.

    The same fire keeps its React key across polls instead of remounting.
    """
    first = client.get("/api/detected-events").json()["events"][0]["id"]
    second = client.get("/api/detected-events").json()["events"][0]["id"]

    assert isinstance(first, str)
    assert first == second


def test_metadata_reports_status_per_service(pipeline):
    response = client.get("/api/detected-events")
    services = response.json()["metadata"]["services"]

    assert services["detection"]["status"] == "success"
    assert services["risk_analysis"]["status"] == "success"
    assert services["response_planning"]["status"] == "success"
    assert services["protocols"]["status"] == "success"


def test_partial_failure_is_reported_without_losing_the_event(pipeline):
    """A planning failure must still leave a risk score on the map."""
    detection, risk, plan = pipeline
    plan.plan_response.return_value = {
        **SKIPPED_PLAN,
        "metadata": {**SKIPPED_PLAN["metadata"], "planning_status": "failed"},
        "error": "timeout",
    }

    response = client.get("/api/detected-events")
    data = response.json()

    assert data["metadata"]["collection_status"] == "partial_service_failure"
    assert len(data["events"]) == 1
    assert data["events"][0]["risk_score"] == 78
    assert data["events"][0]["response_plan"] == []


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------


def test_query_parameters_reach_the_detection_agent(pipeline):
    detection, _, _ = pipeline

    client.get("/api/detected-events?latitude=32.1&longitude=34.9&radius_km=8&day_range=3")

    kwargs = detection.detect_fire.call_args.kwargs

    assert kwargs["latitude"] == 32.1
    assert kwargs["longitude"] == 34.9
    assert kwargs["max_hotspot_distance_km"] == 8
    assert kwargs["day_range"] == 3


@pytest.mark.parametrize(
    "params",
    [
        "latitude=10.0",          # south of Israel
        "latitude=45.0",          # north of Israel
        "longitude=10.0",         # west of Israel
        "longitude=50.0",         # east of Israel
        "day_range=99",           # beyond the allowed window
        "radius_km=500",          # beyond the allowed radius
    ],
)
def test_out_of_range_parameters_are_rejected(pipeline, params):
    """
    Bounds are enforced by FastAPI before any provider is contacted.

    This is what stops the endpoint being used to scan arbitrary parts of the
    world through our upstream providers.
    """
    response = client.get(f"/api/detected-events?{params}")

    assert response.status_code == 422


def test_include_analysis_false_skips_both_model_calls(pipeline):
    """
    The fast path.

    Detection still runs, but neither reasoning agent is invoked, so no
    retrieval and no model tokens are spent.
    """
    detection, risk, plan = pipeline

    response = client.get("/api/detected-events?include_analysis=false")
    data = response.json()

    detection.detect_fire.assert_called_once()
    risk.analyze_event.assert_not_called()
    plan.plan_response.assert_not_called()

    assert response.status_code == 200
    assert data["query"]["include_analysis"] is False


def test_query_is_echoed_back(pipeline):
    """The response states what was actually scanned."""
    response = client.get("/api/detected-events?latitude=32.1&longitude=34.9")

    assert response.json()["query"]["latitude"] == 32.1
    assert response.json()["query"]["longitude"] == 34.9


def test_unexpected_agent_error_is_masked_as_500(pipeline):
    """
    Internal detail must not leak to the client.

    The real exception is logged; the client gets a generic message.
    """
    detection, _, _ = pipeline
    detection.detect_fire.side_effect = RuntimeError("internal path /secret/key")

    response = client.get("/api/detected-events")

    assert response.status_code == 500
    assert "secret" not in response.text
