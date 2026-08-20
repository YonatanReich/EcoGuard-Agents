"""
Tests for the events API.

Covers the health check and the /api/detected-events contract: that the
endpoint responds, returns an events list, and that each event carries the
fields the dashboard depends on (map coordinates and a risk score in range).

These are contract tests, not logic tests — /api/detected-events currently
serves mock data, so they assert the response shape rather than any
particular values. They deliberately avoid /api/environmental-data, which
would make real calls to external providers and take tens of seconds.

Run with: pytest
"""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Put the repository root on sys.path so "backend.main" resolves when pytest
# is invoked from anywhere, not just the project root.
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from backend.main import app

# TestClient calls the app in-process — no running uvicorn server needed.
client = TestClient(app)


def test_root_endpoint_returns_status_200():
    """The health check responds 200 and reports success."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_detected_events_endpoint_returns_status_200():
    """The events endpoint is reachable and does not error."""
    response = client.get("/api/detected-events")

    assert response.status_code == 200


def test_detected_events_response_contains_events_list():
    """The response wraps events in an "events" list with at least one entry.

    The dashboard maps over this list directly, so both the key and the list
    type are part of the contract.
    """
    response = client.get("/api/detected-events")
    data = response.json()

    assert "events" in data
    assert isinstance(data["events"], list)
    assert len(data["events"]) > 0


def test_detected_event_contains_latitude_and_longitude():
    """Every event is placeable on the map.

    Without both coordinates MapView cannot render a marker for the event.
    """
    response = client.get("/api/detected-events")
    event = response.json()["events"][0]

    assert "latitude" in event
    assert "longitude" in event


def test_detected_event_risk_score_is_between_0_and_100():
    """Risk scores stay inside the documented 0-100 band.

    Guards the risk analysis agent's output range, which the UI will
    eventually render as a percentage or gauge.
    """
    response = client.get("/api/detected-events")
    event = response.json()["events"][0]

    assert "risk_score" in event
    assert 0 <= event["risk_score"] <= 100