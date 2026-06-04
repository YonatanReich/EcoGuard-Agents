import sys
from pathlib import Path

from fastapi.testclient import TestClient

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from backend.main import app

client = TestClient(app)


def test_root_endpoint_returns_status_200():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_detected_events_endpoint_returns_status_200():
    response = client.get("/api/detected-events")

    assert response.status_code == 200


def test_detected_events_response_contains_events_list():
    response = client.get("/api/detected-events")
    data = response.json()

    assert "events" in data
    assert isinstance(data["events"], list)
    assert len(data["events"]) > 0


def test_detected_event_contains_latitude_and_longitude():
    response = client.get("/api/detected-events")
    event = response.json()["events"][0]

    assert "latitude" in event
    assert "longitude" in event


def test_detected_event_risk_score_is_between_0_and_100():
    response = client.get("/api/detected-events")
    event = response.json()["events"][0]

    assert "risk_score" in event
    assert 0 <= event["risk_score"] <= 100