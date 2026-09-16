"""Generic projected-event feed tests; no shared database is required."""

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ecoguard.api import events as event_api
from ecoguard.coordinator.event_projection import air_pollution_shared_event
from ecoguard.coordinator.event_projection import project_processing_results
from ecoguard.coordinator.incidents import signal_as_json
from ecoguard.detectors.air_pollution.cell_signal_adapter import (
    air_pollution_detection_to_cell_signal,
)
from ecoguard.database.repositories import event_projections as repository
from ecoguard.tests.coordinator.test_event_projection import _successful_result
from ecoguard.tests.coordinator.test_incident_dispatcher import (
    REQUESTED_AT,
    _working_handler,
)
from ecoguard.tests.detectors.air_pollution.test_observation_processing import (
    processor,
    row as persisted_observation_row,
)

NOW = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)


def _row(*, incident_id=None, payload=None, **overrides):
    incident, result = _successful_result()
    event = air_pollution_shared_event(result, incident)
    values = {
        "incident_id": incident_id or incident["id"],
        "hazard": "air_pollution",
        "route": "non_emergency",
        "processing_status": "partial",
        "analysis_status": "partial",
        "planner_status": "success",
        "event_payload": payload or event.model_dump(mode="json"),
        "last_successful_event_payload": event.model_dump(mode="json"),
        "failure_stage": None,
        "failure_reason": None,
        "retryable": False,
        "attempt_count": 1,
        "last_attempt_at": NOW,
        "processed_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return values


def test_api_returns_projected_air_pollution_advisory(monkeypatch):
    monkeypatch.setattr(event_api, "read_projected_events", lambda *, limit: [_row()])
    application = FastAPI()
    application.include_router(event_api.router)

    response = TestClient(application).get("/api/events")

    assert response.status_code == 200
    event = response.json()["events"][0]
    assert event["id"] == "INC-AP-1"
    assert event["type"] == "air_pollution"
    assert event["classification"] == "advisory"
    assert event["processing"]["route"] == "non_emergency"
    assert event["details"]["historical_baseline"]["p95"] == 20.0
    assert event["details"]["trend"] == "RISING"
    assert len(event["details"]["recommendations"]) == 1


def test_latest_failed_projection_uses_honest_fallback_without_old_recommendations():
    row = _row(
        failure_stage="projection",
        failure_reason="ValidationError",
        retryable=True,
        processing_status="failed",
        attempt_count=2,
    )

    event = event_api.shared_event_feed([row]).events[0]

    assert event.id == row["incident_id"]
    assert event.processing.status == "failed"
    assert event.processing.using_last_successful_payload is True
    assert event.processing.failure_reason == "ValidationError"
    assert event.details.recommendations == []
    assert event.details.verified_references == []
    assert any(
        item.component == "event_projection"
        for item in event.details.unavailable_components
    )


def test_partial_planner_failure_remains_visible_without_recommendations():
    row = _row()
    row["event_payload"]["planning_status"] = "failed"
    row["event_payload"]["details"]["recommendations"] = []
    row["event_payload"]["details"]["verified_references"] = []
    row["processing_status"] = "partial"
    row["planner_status"] = "failed"
    row["failure_stage"] = "planning"
    row["failure_reason"] = "model_failure"
    row["retryable"] = True

    event = event_api.shared_event_feed([row]).events[0]

    assert event.classification == "advisory"
    assert event.planning_status == "failed"
    assert event.details.recommendations == []
    assert event.processing.failure_stage == "planning"


def test_empty_and_unusable_projections_produce_an_empty_feed():
    assert event_api.shared_event_feed([]).events == []
    assert event_api.shared_event_feed([{
        "incident_id": "INC-BROKEN",
        "event_payload": None,
        "last_successful_event_payload": None,
    }]).events == []


def test_feed_preserves_repository_order_and_rejects_identity_mismatch():
    first = _row()
    second_payload = dict(first["event_payload"])
    second_payload["id"] = "INC-AP-2"
    second = _row(incident_id="INC-AP-2", payload=second_payload)
    mismatched = _row(incident_id="INC-OTHER")

    feed = event_api.shared_event_feed([second, first, mismatched])

    assert [event.id for event in feed.events] == ["INC-AP-2", "INC-AP-1"]


def test_repository_query_has_stable_order_and_bounded_limit(monkeypatch):
    calls = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, params):
            calls.append((" ".join(str(statement).split()), params))
            return Result()

    monkeypatch.setattr(repository, "Session", Session)

    assert repository.projected_events(limit=25) == []
    assert "ORDER BY updated_at DESC, incident_id ASC" in calls[0][0]
    assert calls[0][1] == {"limit": 25}


def test_persisted_observation_reaches_shared_api_contract(monkeypatch):
    """Small in-memory E2E: real detector, Coordinator, handler and mapper."""

    from ecoguard.coordinator import agent, dispatcher

    detection_service, _ = processor()
    detection = detection_service.process_rows([
        persisted_observation_row(1, 21.0),
    ])[0].detection
    signal = air_pollution_detection_to_cell_signal(detection)

    stored = []

    def open_incidents(hazards=None):
        if hazards is None:
            return list(stored)
        return [item for item in stored if set(item["hazards"]) & set(hazards)]

    def create_incident(identifier, item, queues):
        incident = {
            "id": identifier,
            "status": "open",
            "primary_hazard": item.hazard,
            "hazards": [item.hazard],
            "queues": list(queues),
            "cells": [item.cell_id],
            "latitude": item.location.latitude,
            "longitude": item.location.longitude,
            "precision_m": item.location.precision_m,
            "location_method": item.location.method,
            "first_seen_at": item.observed_at,
            "last_signal_at": item.observed_at,
            "signal_count": 1,
            "links": [],
            "signals": [signal_as_json(item)],
        }
        stored.append(incident)
        return incident

    monkeypatch.setattr(agent.store, "close_quiet", lambda at, policy: [])
    monkeypatch.setattr(agent.store, "open_incidents", open_incidents)
    monkeypatch.setattr(agent.store, "next_incident_id", lambda at: "INC-E2E-1")
    monkeypatch.setattr(agent.store, "create_incident", create_incident)

    coordination = agent.coordinate([signal], at=REQUESTED_AT)
    assert coordination.created == ["INC-E2E-1"]

    handler, _ = _working_handler()
    result = dispatcher.dispatch_incidents(
        stored,
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )[0]
    writes = []
    project_processing_results(
        [result],
        incident_reader=lambda _: stored[0],
        writer=lambda record: writes.append(record),
    )
    record = writes[0]
    feed_row = {
        **record.__dict__,
        "last_successful_event_payload": record.event_payload,
        "attempt_count": 1,
        "last_attempt_at": record.attempted_at,
    }

    event = event_api.shared_event_feed([feed_row]).events[0]

    assert event.id == "INC-E2E-1"
    assert event.type == "air_pollution"
    assert event.classification == "advisory"
    assert event.processing.route == "non_emergency"
    assert event.details.measured_value == 21.0
    assert event.details.historical_baseline.p95 == 20.0
    # The grounded planner rejects this detector-derived synthetic case rather
    # than borrowing fixture-specific citations. Delivery must still succeed.
    assert event.planning_status == "failed"
    assert event.details.recommendations == []
