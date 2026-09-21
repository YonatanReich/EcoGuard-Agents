"""Durable SharedEvent projection mapping and orchestration tests."""

from dataclasses import replace
from datetime import timedelta
import pytest
from sqlalchemy import text

from ecoguard.coordinator.dispatcher import IncidentProcessingResult, dispatch_incidents
from ecoguard.analyzers.emergency.flood.event_analyzer import FloodEventAnalyzer
from ecoguard.analyzers.emergency.flood.risk_analyzer import FloodRiskAnalyzer
from ecoguard.coordinator.incidents import signal_as_json
from ecoguard.coordinator.event_projection import (
    air_pollution_shared_event,
    flood_shared_event,
    project_processing_results,
)
from ecoguard.detectors.air_pollution.cell_signal_adapter import (
    air_pollution_candidate_to_cell_signal,
)
from ecoguard.detectors.air_pollution.correlation import PollutionCorrelationCandidate
from ecoguard.database.repositories import event_projections as repository
from ecoguard.database.repositories.event_projections import EventProjectionWrite
from ecoguard.response_planner.air_pollution.schemas import (
    AirPollutionPlanningResult,
    AirPollutionResponsePlan,
)
from ecoguard.tests.coordinator.test_incident_dispatcher import (
    REQUESTED_AT,
    _incident,
    _working_handler,
)


def _successful_result():
    incident, _ = _incident()
    handler, _ = _working_handler()
    result = dispatch_incidents(
        [incident],
        registry={("air_pollution", "non_emergency"): handler},
        at=REQUESTED_AT,
    )[0]
    return incident, result


def test_successful_result_maps_to_frontend_shared_event_contract():
    incident, result = _successful_result()

    event = air_pollution_shared_event(result, incident)

    assert event.id == incident["id"]
    assert event.type == "air_pollution"
    assert event.classification == "advisory"
    assert event.analysis_status == "partial"
    assert event.planning_status == "success"
    assert event.details.pollutant == "NO2"
    assert event.details.measured_value == 21.0
    assert event.details.unit == "ppb"
    assert event.details.historical_baseline.p95 == 20.0
    assert "severity" not in event.details.model_dump()
    assert "source_location" not in event.model_dump()
    assert event.details.ministry_aqi.station_index == 67.0
    assert event.details.ministry_aqi.station_id == "42"
    assert event.details.ministry_aqi.pollutant == "NO2"
    assert event.details.ministry_aqi.resolved_channel_id == "7001"
    assert event.details.official_pollutant_classification.classification == "GOOD"
    assert event.details.official_pollutant_classification.pollutant_sub_index == 71.0
    assert event.details.publication_policy.publish_to_operational_dashboard is False
    assert event.details.additional_verification is None
    assert event.details.trend == "RISING"
    assert event.details.transport.corridor.type == "Polygon"
    assert event.details.settlement_context.outcome == "SUCCESS_WITH_RESULTS"
    assert event.details.population_within_screening_corridor.total_relevant_population == 50
    assert len(event.details.recommendations) == 1
    assert len(event.details.verified_references) == 1
    assert any("not health severity" in item for item in event.details.limitations)
    assert any("not a confirmed emission source" in item for item in event.details.limitations)
    assert any("not confirmed affected or exposed" in item for item in event.details.limitations)


def test_flood_result_projects_stream_station_and_distinct_road_locations():
    result = IncidentProcessingResult(
        incident_id="INC-FLOOD-1",
        hazard="flood",
        route="emergency",
        status="success",
        requested_at=REQUESTED_AT,
        completed_at=REQUESTED_AT,
        planner_result={
            "response_actions": [{
                "action": "Close access to the flooded road.",
                "responsible_unit": "police",
                "timeframe": "immediate",
                "supporting_protocol_chunk_ids": ["flood-protocol#0"],
            }],
            "assumptions": ["The road remains accessible to responders."],
            "evidence_gaps": ["No confirmed trapped-person report."],
            "limitations": ["Field conditions may change rapidly."],
        },
        resource_allocation_result={
            "status": "targets_identified",
            "hydrometric_sources": [{
                "station": {
                    "id": 50,
                    "latitude": 31.1,
                    "longitude": 35.2,
                    "precision_m": 12.0,
                    "severity_level": 5,
                    "observed_at": REQUESTED_AT.isoformat(),
                    "stream_match": "matched",
                },
                "strategy": "matched_stream",
                "stream": {
                    "stream_id": 7,
                    "water_source_id": 70,
                    "stream_name": "Test stream",
                    "match_confidence": "high",
                    "geometry": {
                        "type": "MultiLineString",
                        "coordinates": [[[35.1, 31.0], [35.3, 31.2]]],
                    },
                },
            }],
            "response_sites": [{
                "target_id": "flood-road-1",
                "source_station_id": 50,
                "severity_level": 5,
                "strategy": "matched_stream",
                "road": {
                    "segment_id": 3,
                    "source": "mapbox",
                    "source_feature_id": "road-3",
                    "class": "primary",
                    "base_class": "primary",
                    "name": "Road 1",
                    "ref": "1",
                    "bridge": False,
                    "tunnel": False,
                    "vehicle_access": "yes",
                },
                "crossing_type": "at_grade",
                "urban": False,
                "crossing_location": {"latitude": 31.11, "longitude": 35.21},
                "allocation_location": {"latitude": 31.111, "longitude": 35.211},
                "allocation_eligible": True,
                "local_match_confidence": "high",
                "mapbox_verification": {
                    "status": "verified",
                    "verified": True,
                    "reason": None,
                    "mapbox_snap_distance_m": 8.0,
                },
            }],
            "advisories": [{
                "type": "stream_access_warning",
                "action": "warn_and_restrict_stream_access",
                "scope": "affected_stream",
                "instruction": "Close the stream to visitors.",
            }],
        },
    )

    event = flood_shared_event(result, {"id": "INC-FLOOD-1", "signals": []})

    assert event.type == "flood"
    assert event.details.severity_level == 5
    assert event.details.sources[0].stream.water_source_id == 70
    assert event.details.sources[0].stream.geometry.type == "MultiLineString"
    assert event.details.response_sites[0].road.road_class == "primary"
    assert event.details.response_sites[0].crossing_location.longitude == 35.21
    assert event.details.response_sites[0].allocation_location.longitude == 35.211
    assert event.details.response_actions[0].responsible_unit == "police"
    assert event.details.assumptions == [
        "The road remains accessible to responders."
    ]
    assert event.details.evidence_gaps == [
        "No confirmed trapped-person report."
    ]
    assert "Field conditions may change rapidly." in event.details.limitations


def test_flood_deescalation_projects_current_band_and_preserves_response():
    thresholds = [20.0, 35.0, 50.0, 80.0, 120.0, 170.0]

    def signal(observed_at, discharge, severity, previous):
        return {
            "cell_id": "31.75:35.20",
            "observed_at": observed_at.isoformat(),
            "hazard": "flood",
            "value": discharge,
            "confidence": 0.9,
            "location": {
                "latitude": 31.75,
                "longitude": 35.2,
                "precision_m": 75.0,
            },
            "evidence": {
                "source_station_id": 417,
                "stream_id": 82,
                "current_discharge": discharge,
                "severity_level": severity,
                "threshold_vector_m3s": thresholds,
                "recent_discharges_m3s": [previous, discharge],
            },
        }

    later = REQUESTED_AT + timedelta(minutes=10)
    incident = {
        "id": "INC-FLOOD-DEESCALATED",
        "signals": [
            signal(REQUESTED_AT, 125.0, 5, 122.0),
            signal(later, 85.0, 4, 125.0),
        ],
    }
    analysis = FloodEventAnalyzer(clock=lambda: later).analyze(incident)
    risk = FloodRiskAnalyzer(clock=lambda: later).analyze(analysis)
    result = IncidentProcessingResult(
        incident_id=incident["id"],
        hazard="flood",
        route="emergency",
        status="success",
        requested_at=later,
        completed_at=later,
        analysis_status=analysis.status,
        risk_status=risk.metadata.analysis_status,
        planner_status="skipped",
        analysis_result=analysis,
        risk_assessment=risk,
        response_refresh_required=False,
        requires_resource_allocation=False,
        preserve_existing_response=True,
    )

    event = flood_shared_event(result, incident)

    assert event.details.severity_level == 4
    assert event.details.return_period_label == "20-year"
    assert event.details.risk_status == "success"
    assert event.details.risk_score == 60
    assert event.details.risk_level == "high"
    assert event.details.risk_confidence == "high"
    assert event.details.sources[0].station.severity_level == 4
    assert event.details.sources[0].station.precision_m == 75.0
    assert event.details.change_type == "deescalated"
    assert event.details.threshold_transition == "Q50_to_Q20"
    assert event.details.response_refresh_required is False
    assert event.details.existing_response_preserved is True
    assert event.details.targeting_status == "preserved_existing_response"
    assert event.planning_status == "skipped"

    previous_plan = {
        "incident_id": incident["id"],
        "hazard_type": "flood",
        "plan_summary": "Keep the existing road closure and command structure.",
    }
    previous_site = {
        "target_id": "flood-road-existing",
        "source_station_id": 417,
        "severity_level": 5,
        "strategy": "matched_stream",
        "road": {"name": "Road 1", "road_class": "primary"},
        "crossing_type": "at_grade",
        "urban": False,
        "crossing_location": {"latitude": 31.76, "longitude": 35.21},
        "allocation_location": {"latitude": 31.761, "longitude": 35.211},
        "allocation_eligible": True,
        "local_match_confidence": "high",
        "mapbox_verification": {
            "status": "verified",
            "verified": True,
            "reason": None,
            "mapbox_snap_distance_m": 8.0,
        },
    }
    writes = []
    project_processing_results(
        [result],
        incident_reader=lambda _: incident,
        projection_reader=lambda _: {
            "last_successful_event_payload": {
                "details": {
                    "response_sites": [previous_site],
                    "allocation_ready_site_ids": ["flood-road-existing"],
                    "targeting_reason": "existing_target",
                    "allocation_target": {"latitude": 31.761, "longitude": 35.211},
                    "advisories": [],
                    "resource_allocation": None,
                    "response_plan": previous_plan,
                }
            }
        },
        writer=lambda record: writes.append(record),
    )

    projected = writes[0].event_payload
    assert projected["details"]["severity_level"] == 4
    assert projected["details"]["response_sites"][0]["target_id"] == "flood-road-existing"
    assert projected["details"]["response_plan"] == previous_plan
    assert projected["details"]["existing_response_preserved"] is True


def test_planner_failure_has_no_fabricated_recommendations():
    incident, result = _successful_result()
    result.status = "partial"
    result.planner_status = "failed"
    result.planner_result = AirPollutionPlanningResult(
        analysis=result.analysis_result,
        plan=AirPollutionResponsePlan(
            status="failed",
            reason="model_failure",
            limitations=["Planner failed closed."],
        ),
    )

    event = air_pollution_shared_event(result, incident)

    assert event.planning_status == "failed"
    assert event.details.recommendations == []
    assert event.details.verified_references == []
    assert any(
        item.component == "planner" and item.reason == "model_failure"
        for item in event.details.unavailable_components
    )


def test_analysis_failure_projects_preserved_incident_evidence_honestly():
    incident, _ = _incident()
    result = IncidentProcessingResult(
        incident_id=incident["id"],
        hazard="air_pollution",
        route="non_emergency",
        status="failed",
        requested_at=REQUESTED_AT,
        completed_at=REQUESTED_AT,
        analysis_status=None,
        planner_status=None,
        failure_stage="analysis",
        failure_reason="RuntimeError",
    )

    event = air_pollution_shared_event(result, incident)

    assert event.analysis_status == "failed"
    assert event.planning_status == "skipped"
    assert event.details.historical_baseline.p95 == 20.0
    assert event.details.ministry_aqi is None
    assert event.details.trend is None
    assert event.details.recommendations == []
    assert any(
        item.component == "analysis" and item.reason == "RuntimeError"
        for item in event.details.unavailable_components
    )

    writes = []
    project_processing_results(
        [result],
        incident_reader=lambda _: incident,
        writer=lambda record: writes.append(record),
    )
    assert writes[0].analysis_status == "failed"
    assert writes[0].planner_status == "skipped"
    assert writes[0].retryable is True


def test_unloaded_locality_state_projects_even_when_transport_did_not_run():
    incident, candidate = _incident()
    payload = candidate.model_dump(round_trip=True)
    payload["spatial_context"].update({
        "status": "unavailable",
        "provider_collection_status": "REFERENCE_DATA_NOT_LOADED",
        "settlement_context": {
            "status": "unavailable",
            "outcome": "REFERENCE_DATA_NOT_LOADED",
            "candidate_count": 0,
            "reason": "reference_data_not_loaded",
        },
        "nearby_settlements": [],
    })
    unavailable_candidate = PollutionCorrelationCandidate.model_validate(payload)
    incident["signals"] = [
        signal_as_json(air_pollution_candidate_to_cell_signal(unavailable_candidate))
    ]
    result = IncidentProcessingResult(
        incident_id=incident["id"],
        hazard="air_pollution",
        route="non_emergency",
        status="failed",
        requested_at=REQUESTED_AT,
        completed_at=REQUESTED_AT,
        failure_stage="analysis",
        failure_reason="RuntimeError",
    )

    event = air_pollution_shared_event(result, incident)

    assert event.details.transport is None
    assert event.details.relevant_settlements == []
    assert event.details.settlement_context.status == "unavailable"
    assert event.details.settlement_context.reason == "reference_data_not_loaded"


def test_same_incident_is_upserted_as_one_projection_and_latest_wins():
    incident, result = _successful_result()
    stored = {}
    writes = []

    def writer(record):
        writes.append(record)
        previous = stored.get(record.incident_id, {})
        stored[record.incident_id] = {
            **previous,
            "incident_id": record.incident_id,
            "event_payload": record.event_payload,
            "attempt_count": previous.get("attempt_count", 0) + 1,
            "processing_status": record.processing_status,
        }
        return dict(stored[record.incident_id])

    kwargs = {
        "incident_reader": lambda _: incident,
        "writer": writer,
    }
    project_processing_results([result], **kwargs)
    newer = replace(
        result,
        status="failed",
        analysis_status=None,
        planner_status=None,
        analysis_result=None,
        planner_result=None,
        failure_stage="analysis",
        failure_reason="temporary_failure",
    )
    project_processing_results([newer], **kwargs)

    assert list(stored) == [incident["id"]]
    assert stored[incident["id"]]["attempt_count"] == 2
    assert stored[incident["id"]]["processing_status"] == "failed"
    assert stored[incident["id"]]["event_payload"]["analysis_status"] == "failed"
    assert stored[incident["id"]]["event_payload"]["details"]["recommendations"] == []
    assert len(writes) == 2
    assert all(item.incident_id == incident["id"] for item in writes)


def test_unsupported_fire_result_creates_no_air_pollution_projection():
    writes = []
    result = IncidentProcessingResult(
        incident_id="INC-FIRE-1",
        hazard="fire",
        route="emergency",
        status="skipped",
        requested_at=REQUESTED_AT,
        completed_at=REQUESTED_AT,
        failure_reason="unsupported_hazard_route",
    )

    outcomes = project_processing_results(
        [result],
        incident_reader=lambda _: pytest.fail("Fire skip must not load incident"),
        writer=lambda record: writes.append(record),
    )

    assert outcomes[0].status == "skipped"
    assert writes == []


def test_projection_persistence_failure_is_isolated_per_incident():
    incident_a, result_a = _successful_result()
    incident_b = {**incident_a, "id": "INC-AP-2"}
    result_b = replace(result_a, incident_id="INC-AP-2")
    persisted = []

    def writer(record):
        if record.incident_id == incident_a["id"]:
            raise RuntimeError("database unavailable")
        persisted.append(record.incident_id)

    outcomes = project_processing_results(
        [result_a, result_b],
        incident_reader=lambda identifier: (
            incident_a if identifier == incident_a["id"] else incident_b
        ),
        writer=writer,
    )

    assert [item.persisted for item in outcomes] == [False, True]
    assert persisted == ["INC-AP-2"]


def test_repository_upsert_sql_preserves_identity_and_increments_attempt(monkeypatch):
    statements = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, params):
            statements.append((str(statement), params))

        def commit(self):
            pass

    monkeypatch.setattr(repository, "Session", Session)
    monkeypatch.setattr(
        repository,
        "event_projection_by_incident",
        lambda incident_id: {"incident_id": incident_id},
    )
    record = EventProjectionWrite(
        incident_id="INC-AP-1",
        hazard="air_pollution",
        route="non_emergency",
        processing_status="partial",
        analysis_status="partial",
        planner_status="success",
        analysis_id="analysis:test",
        coordinator_routing_id="routing:test",
        handler="air_pollution_non_emergency",
        event_payload={"id": "INC-AP-1"},
        failure_stage=None,
        failure_reason=None,
        retryable=False,
        successful=True,
        attempted_at=REQUESTED_AT,
        processed_at=REQUESTED_AT,
    )

    repository.upsert_event_projection(record)
    sql = " ".join(statements[0][0].split())

    assert "ON CONFLICT (incident_id) DO UPDATE" in sql
    assert "attempt_count = event_projections.attempt_count + 1" in sql
    assert "ELSE event_projections.last_successful_event_payload" in sql
    assert "created_at" not in sql.split("DO UPDATE SET", 1)[1]
    assert statements[0][1]["incident_id"] == "INC-AP-1"
    assert statements[0][1]["route"] == "non_emergency"
    assert statements[0][1]["analysis_id"] == "analysis:test"


def test_projection_survives_repository_reload_when_database_is_available(database):
    with database.connect() as connection:
        exists = connection.execute(
            text("SELECT to_regclass('event_projections')")
        ).scalar_one()
    if exists is None:
        pytest.skip("event_projections migration is not applied")

    incident_id = "INC-PROJECTION-RELOAD-TEST"
    with database.connect() as connection:
        connection.execute(text("DELETE FROM event_projections WHERE incident_id=:id"), {"id": incident_id})
        connection.execute(text("DELETE FROM incidents WHERE id=:id"), {"id": incident_id})
        connection.execute(text("""
            INSERT INTO incidents (
              id, status, primary_hazard, hazards, queues, cells,
              first_seen_at, last_signal_at, signal_count
            ) VALUES (
              :id, 'open', 'air_pollution', ARRAY['air_pollution'],
              ARRAY['non_emergency'], ARRAY['ISR-001-001'], :at, :at, 1
            )
        """), {"id": incident_id, "at": REQUESTED_AT})
        connection.commit()
    try:
        record = EventProjectionWrite(
            incident_id=incident_id,
            hazard="air_pollution",
            route="non_emergency",
            processing_status="partial",
            analysis_status="partial",
            planner_status="success",
            analysis_id="analysis:test",
            coordinator_routing_id="routing:test",
            handler="air_pollution_non_emergency",
            event_payload={"id": incident_id, "type": "air_pollution"},
            failure_stage=None,
            failure_reason=None,
            retryable=False,
            successful=True,
            attempted_at=REQUESTED_AT,
            processed_at=REQUESTED_AT,
        )
        repository.upsert_event_projection(record)
        reloaded = repository.event_projection_by_incident(incident_id)
        assert reloaded["incident_id"] == incident_id
        assert reloaded["event_payload"]["type"] == "air_pollution"
    finally:
        with database.connect() as connection:
            connection.execute(text("DELETE FROM event_projections WHERE incident_id=:id"), {"id": incident_id})
            connection.execute(text("DELETE FROM incidents WHERE id=:id"), {"id": incident_id})
            connection.commit()
