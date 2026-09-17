"""Generic projected-event feed tests; no shared database is required."""

from datetime import datetime, timedelta, timezone

import pytest
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


def _incident_signal(
    detection_id: str,
    *,
    observed_at: datetime = NOW,
    cell_id: str = "risk-05000m-r0055-c0013",
    source: str = "israel_ministry_environment_air_monitoring",
    station_id: str = "42",
    channel_id: str = "7001",
    pollutant: str = "NO2",
):
    return {
        "hazard": "air_pollution",
        "cell_id": cell_id,
        "observed_at": observed_at.isoformat(),
        "source": source,
        "evidence": {
            "correlation_candidate": {
                "anomaly": {
                    "detection_id": detection_id,
                    "station_id": station_id,
                    "channel_id": channel_id,
                    "pollutant": pollutant,
                },
            },
        },
    }


def _row(*, incident_id=None, payload=None, **overrides):
    incident, result = _successful_result()
    event = air_pollution_shared_event(result, incident)
    event_payload = payload or event.model_dump(mode="json")
    if event_payload.get("type") == "air_pollution":
        # EA-371 operational display threshold: use an official MODERATE
        # pollutant-specific sub-index unless a test supplies another value.
        event_payload["details"]["ministry_aqi"]["pollutant_sub_index"] = 25.0
    station = event.details.station
    observed_at = event.details.observation_timestamp
    values = {
        "incident_id": incident_id or incident["id"],
        "hazard": "air_pollution",
        "route": "non_emergency",
        "processing_status": "partial",
        "analysis_status": "partial",
        "planner_status": "success",
        "event_payload": event_payload,
        "last_successful_event_payload": event.model_dump(mode="json"),
        "failure_stage": None,
        "failure_reason": None,
        "retryable": False,
        "attempt_count": 1,
        "last_attempt_at": NOW,
        "processed_at": NOW,
        "updated_at": NOW,
        "incident_signals": [
            _incident_signal(
                "detector-1",
                observed_at=observed_at,
                source=station.provider,
                station_id=station.id,
                channel_id=station.channel_id,
                pollutant=event.details.pollutant,
            ),
            _incident_signal(
                "detector-2",
                observed_at=observed_at + timedelta(minutes=5),
                source=station.provider,
                station_id="43",
                channel_id=station.channel_id,
                pollutant=event.details.pollutant,
            ),
        ],
    }
    values.update(overrides)
    return values


def _persistent_row(*, pollutant_sub_index: float):
    row = _row()
    details = row["event_payload"]["details"]
    observed_at = datetime.fromisoformat(details["observation_timestamp"])
    station = details["station"]
    pollutant = details["pollutant"]
    row["incident_signals"] = [
        _incident_signal(
            "detector-1",
            observed_at=observed_at - timedelta(minutes=5),
            station_id=station["id"],
            channel_id=station["channel_id"],
            pollutant=pollutant,
        ),
        _incident_signal(
            "detector-2",
            observed_at=observed_at,
            station_id=station["id"],
            channel_id=station["channel_id"],
            pollutant=pollutant,
        ),
    ]
    details["ministry_aqi"]["pollutant_sub_index"] = pollutant_sub_index
    return row


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


def test_latest_failed_projection_uses_qualified_old_payload_without_recommendations():
    row = _row(
        failure_stage="projection",
        failure_reason="ValidationError",
        retryable=True,
        processing_status="failed",
        attempt_count=2,
    )

    event = event_api.shared_event_feed([row]).events[0]

    assert event.id == row["incident_id"]
    assert event.processing.using_last_successful_payload is True
    assert event.details.recommendations == []
    assert event.details.verified_references == []


def test_qualified_event_with_unavailable_planner_is_still_published():
    row = _row()
    row["event_payload"]["planning_status"] = "failed"
    row["event_payload"]["details"]["recommendations"] = []
    row["event_payload"]["details"]["verified_references"] = []
    row["processing_status"] = "partial"
    row["planner_status"] = "failed"
    row["failure_stage"] = "planning"
    row["failure_reason"] = "model_unavailable"
    row["retryable"] = True
    row["event_payload"]["details"]["unavailable_components"] = [{
        "component": "planner",
        "reason": "model_unavailable",
    }]

    event = event_api.shared_event_feed([row]).events[0]

    assert event.planning_status == "failed"
    assert event.details.recommendations == []
    assert event.details.verified_references == []
    assert any(
        item.component == "planner" and item.reason == "model_unavailable"
        for item in event.details.unavailable_components
    )


def test_p95_only_suspected_anomaly_is_not_published():
    row = _row()
    row["incident_signals"] = row["incident_signals"][:1]

    assert event_api.shared_event_feed([row]).events == []


def test_different_pollutants_do_not_spatially_corroborate_publication():
    row = _row()
    row["incident_signals"][1]["evidence"]["correlation_candidate"]["anomaly"][
        "pollutant"
    ] = "SO2"

    assert event_api.shared_event_feed([row]).events == []


def test_same_pollutant_at_different_stations_qualifies_path_a():
    assert len(event_api.shared_event_feed([_row()]).events) == 1


def test_qualified_good_event_is_retained_in_projection_but_not_published():
    row = _row()
    row["event_payload"]["details"]["ministry_aqi"]["pollutant_sub_index"] = 75.0

    assert row["event_payload"] is not None
    assert event_api.shared_event_feed([row]).events == []


def test_qualified_unknown_official_classification_is_not_published():
    row = _row()
    row["event_payload"]["details"]["ministry_aqi"] = None

    assert event_api.shared_event_feed([row]).events == []


def test_historical_projection_without_ea371_fields_still_loads():
    row = _row()
    details = row["event_payload"]["details"]
    details.pop("official_pollutant_classification", None)
    details.pop("publication_policy", None)
    details.pop("additional_verification", None)

    event = event_api.shared_event_feed([row]).events[0]

    assert event.details.official_pollutant_classification is None
    assert event.details.publication_policy is None
    assert event.details.additional_verification is None


def test_station_wide_category_does_not_override_matching_pollutant_sub_index():
    row = _row()
    index = row["event_payload"]["details"]["ministry_aqi"]
    index["station_category"] = "טובה"
    index["station_index"] = 80.0
    index["driving_pollutant"] = "O3"
    index["pollutant_sub_index"] = 25.0

    assert len(event_api.shared_event_feed([row]).events) == 1


@pytest.mark.parametrize(
    "verification_status",
    ["NO_EXTERNAL_EVIDENCE", "VERIFICATION_UNAVAILABLE"],
)
def test_low_event_remains_visible_for_non_corroborating_verification_states(
    verification_status,
):
    row = _row()
    details = row["event_payload"]["details"]
    details["ministry_aqi"]["pollutant_sub_index"] = -25.0
    details["additional_verification"] = {
        "status": verification_status,
        "checked_at": NOW.isoformat(),
        "providers_checked": ["NASA FIRMS", "IMS"],
        "evidence_references": [],
        "reason": "test_verification_state",
        "limitations": ["Possible source correlation only."],
        "possible_source_correlations": [],
    }

    event = event_api.shared_event_feed([row]).events[0]

    assert event.details.additional_verification.status == verification_status
    assert event.classification == "advisory"


def test_same_station_persistence_without_negative_pollutant_aqi_is_internal():
    row = _persistent_row(pollutant_sub_index=1.0)

    assert event_api.shared_event_feed([row]).events == []


def test_same_station_persistence_with_negative_matching_pollutant_aqi_qualifies():
    row = _persistent_row(pollutant_sub_index=-1.0)

    assert len(event_api.shared_event_feed([row]).events) == 1


def test_overall_station_aqi_driven_by_another_pollutant_does_not_qualify():
    row = _persistent_row(pollutant_sub_index=94.0)
    index = row["event_payload"]["details"]["ministry_aqi"]
    index["station_index"] = -5.0
    index["driving_pollutant"] = "O3"

    assert event_api.shared_event_feed([row]).events == []


def test_negative_sub_index_for_different_pollutant_does_not_qualify():
    row = _persistent_row(pollutant_sub_index=-1.0)
    row["event_payload"]["details"]["ministry_aqi"]["pollutant"] = "O3"

    assert event_api.shared_event_feed([row]).events == []


def test_successful_grounded_planner_enriches_qualified_event():
    event = event_api.shared_event_feed([_row()]).events[0]

    assert event.planning_status == "success"
    assert len(event.details.recommendations) == 1
    assert len(event.details.verified_references) == 1


def test_repeated_copy_of_one_detection_is_not_corroboration():
    row = _row()
    row["incident_signals"][1]["evidence"]["correlation_candidate"]["anomaly"][
        "detection_id"
    ] = "detector-1"

    assert event_api.shared_event_feed([row]).events == []


def test_empty_and_unusable_projections_produce_an_empty_feed():
    assert event_api.shared_event_feed([]).events == []
    assert event_api.shared_event_feed([{
        "incident_id": "INC-BROKEN",
        "event_payload": None,
        "last_successful_event_payload": None,
    }]).events == []


def test_fire_publication_is_unaffected_by_air_pollution_qualification():
    payload = {
        "id": "INC-FIRE-1",
        "type": "fire",
        "title": "Fire event",
        "description": "Existing fire projection",
        "latitude": 31.8,
        "longitude": 34.9,
        "observed_at": NOW.isoformat(),
        "classification": "emergency",
        "analysis_status": "success",
        "planning_status": "failed",
        "details": {},
    }
    row = _row(
        incident_id="INC-FIRE-1",
        payload=payload,
        hazard="fire",
        route="emergency",
        planner_status="failed",
        incident_signals=[],
    )

    event = event_api.shared_event_feed([row]).events[0]

    assert event.id == "INC-FIRE-1"
    assert event.type == "fire"


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
    assert "JOIN incidents ON incidents.id = event_projections.incident_id" in calls[0][0]
    assert "incidents.signals AS incident_signals" in calls[0][0]
    assert (
        "ORDER BY event_projections.updated_at DESC, "
        "event_projections.incident_id ASC"
    ) in calls[0][0]
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
        "incident_signals": stored[0]["signals"],
    }

    # The grounded planner rejects this detector-derived synthetic case rather
    # than borrowing fixture-specific citations. Its p95-only candidate remains
    # persisted for audit, but is not a user-facing advisory.
    assert record.event_payload is not None
    assert record.planner_status == "failed"
    assert record.event_payload["details"]["recommendations"] == []
    assert event_api.shared_event_feed([feed_row]).events == []
