"""The weak-event endpoints, with the store stubbed; no database required."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ecoguard.api import weak_events as api

def row(**overrides):
    # Relative to the real clock, because the endpoint counts down against
    # `datetime.now()`. Pinning these to a fixed date made the countdown
    # negative as soon as that date passed, which is a broken test rather
    # than a broken endpoint.
    now = datetime.now(timezone.utc)
    base = {
        "id": "WEAK-20260921-0001",
        "hazard": "fire",
        "status": "open",
        "latitude": 32.794,
        "longitude": 34.989,
        "precision_m": 2000.0,
        "location_text": "חיפה",
        "first_seen_at": now - timedelta(minutes=30),
        "last_seen_at": now - timedelta(minutes=5),
        "expires_at": now + timedelta(hours=2, minutes=30),
        "reports": [{
            "source_id": "telegram:-1001411503185",
            "tier": "unofficial",
            "claim": "fire reported near the Carmel",
            "location_text": "חיפה",
            "observed_at": (now - timedelta(minutes=30)).isoformat(),
        }],
    }
    return {**base, **overrides}


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_the_feed_says_what_would_confirm_each_report(client, monkeypatch):
    # §4's promotion rules, spelled out on the card rather than left as
    # knowledge an operator is expected to already have.
    monkeypatch.setattr(api.store, "open_weak_events", lambda: [row()])

    body = client.get("/api/weak-events").json()

    assert len(body["weak_events"]) == 1
    weak = body["weak_events"][0]
    assert weak["id"] == "WEAK-20260921-0001"
    assert len(weak["would_confirm"]) == 3
    assert any("satellite" in item for item in weak["would_confirm"])
    # The countdown the card renders, not a raw timestamp it has to subtract.
    assert 0 < weak["expires_in_seconds"] <= 2 * 3600 + 30 * 60


def test_each_hazard_names_its_own_instrument_evidence(client, monkeypatch):
    # Telling a flood operator to wait for a satellite hotspot would be wrong
    # and would teach them to ignore the line.
    monkeypatch.setattr(api.store, "open_weak_events", lambda: [row(hazard="flood")])

    weak = client.get("/api/weak-events").json()["weak_events"][0]

    assert any("gauge" in item for item in weak["would_confirm"])
    assert not any("satellite" in item for item in weak["would_confirm"])


def test_the_reporting_sources_and_their_tiers_reach_the_card(client, monkeypatch):
    # "Two local channels said so" and "the police said so" are different
    # claims, and the operator is the one deciding between them.
    monkeypatch.setattr(api.store, "open_weak_events", lambda: [row()])

    weak = client.get("/api/weak-events").json()["weak_events"][0]

    assert weak["reports"][0]["tier"] == "unofficial"
    assert weak["reports"][0]["source_id"] == "telegram:-1001411503185"


def test_confirming_records_the_operator(client, monkeypatch):
    recorded = {}
    monkeypatch.setattr(api.store, "open_weak_events", lambda: [row()])
    monkeypatch.setattr(
        api.store, "resolve_weak_event",
        lambda weak_id, **kwargs: recorded.update({"id": weak_id, **kwargs}),
    )

    response = client.post(
        "/api/weak-events/WEAK-20260921-0001/confirm",
        json={"operator": "y.reich"},
    )

    assert response.status_code == 200
    assert recorded["status"] == "confirmed"
    assert recorded["operator"] == "y.reich"
    assert "y.reich" in recorded["resolution"]


def test_dismissing_records_the_operator_too(client, monkeypatch):
    recorded = {}
    monkeypatch.setattr(api.store, "open_weak_events", lambda: [row()])
    monkeypatch.setattr(
        api.store, "resolve_weak_event",
        lambda weak_id, **kwargs: recorded.update(kwargs),
    )

    response = client.post(
        "/api/weak-events/WEAK-20260921-0001/dismiss",
        json={"operator": "y.reich"},
    )

    assert response.status_code == 200
    assert recorded["status"] == "dismissed"


def test_a_decision_needs_a_named_operator(client, monkeypatch):
    # "Somebody clicked" is not a record. An empty name is rejected by the
    # schema rather than stored as an empty string.
    monkeypatch.setattr(api.store, "open_weak_events", lambda: [row()])

    assert client.post(
        "/api/weak-events/WEAK-20260921-0001/confirm", json={"operator": ""}
    ).status_code == 422
    assert client.post(
        "/api/weak-events/WEAK-20260921-0001/confirm", json={}
    ).status_code == 422


def test_deciding_twice_is_a_404_rather_than_a_silent_overwrite(client, monkeypatch):
    # The second click, or a client holding a stale list. Either way the first
    # decision stands and the second is told the row is gone.
    monkeypatch.setattr(api.store, "open_weak_events", lambda: [])

    response = client.post(
        "/api/weak-events/WEAK-20260921-0001/dismiss", json={"operator": "y.reich"}
    )

    assert response.status_code == 404


def test_a_store_outage_is_a_503_not_an_empty_map(client, monkeypatch):
    # An empty feed means "nothing unverified", which is a claim. A failure to
    # read must not be rendered as one.
    def boom():
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(api.store, "open_weak_events", boom)

    assert client.get("/api/weak-events").status_code == 503
