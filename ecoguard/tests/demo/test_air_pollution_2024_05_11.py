"""Deterministic contracts for the 11 May 2024 PM10 historical scenario."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from ecoguard.analyzers.air_pollution.official_classification import (
    classify_official_pollutant_sub_index,
    publication_policy,
)
from ecoguard.analyzers.air_pollution.event_analysis_schemas import (
    AirPollutionEventQualification,
)
from ecoguard.analyzers.air_pollution.wind_evidence_service import (
    PERSISTED_WIND_SOURCES,
    PersistedFirstWindEvidenceService,
)
from ecoguard.demo.scenarios.air_pollution_2024_05_11 import (
    DISPLAY_NAME,
    RecordedPlannerModel,
    ReconstructedIndexReplayClient,
    build_rows,
    transport_prediction_service,
)
from ecoguard.demo.scenarios import air_pollution_2024_05_11 as scenario
from ecoguard.planners.air_pollution.planner import AirPollutionResponsePlanner
from ecoguard.shared.air_quality_schemas import AirQualityObservation
from ecoguard.shared.cells import are_adjacent, cell_for
from ecoguard.tests.planners.air_pollution.test_planner import _analysis


def _replace(value, old, new):
    if isinstance(value, dict):
        return {key: _replace(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, old, new) for item in value]
    return new if value == old else value


def test_authentic_cached_points_normalize_to_strict_production_observations():
    rows = build_rows()
    observations = [AirQualityObservation.model_validate(row["payload"]) for row in rows[:2]]

    assert [(item.provider_station_id, item.provider_channel_id) for item in observations] == [
        ("86", "15"), ("87", "15")
    ]
    assert [item.value for item in observations] == [816.2, 773.4]
    assert all(item.pollutant == "PM10" for item in observations)
    assert all(item.provider_pollutant_id == "22" for item in observations)
    assert all(item.valid is True and item.provider_status_id == "1" for item in observations)
    assert all(item.provider_timestamp == "2024-05-11T10:45:00+02:00" for item in observations)
    assert all(item.observed_at.isoformat() == "2024-05-11T08:45:00+00:00" for item in observations)


def test_two_real_stations_share_the_same_production_cell_for_path_a():
    first, second = build_rows()[:2]
    first_cell = cell_for(first["latitude"], first["longitude"])
    second_cell = cell_for(second["latitude"], second["longitude"])

    assert first_cell == second_cell == "risk-05000m-r0074-c0015"
    assert are_adjacent(first_cell, second_cell)


def test_values_strictly_exceed_audited_active_may_hour_p95_values():
    first, second = build_rows()[:2]

    assert first["payload"]["value"] > 72.5
    assert second["payload"]["value"] > 77.805


def test_seed_writes_only_source_observations_to_the_explicit_schema(monkeypatch):
    executed = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, statement, parameters):
            executed.append((str(statement), parameters))

        def commit(self):
            return None

    monkeypatch.setattr(scenario, "Session", FakeSession)
    seeded = scenario.seed(
        scenario.SCENARIO_ID,
        now=datetime(2026, 10, 4, tzinfo=timezone.utc),
    )

    assert seeded["observations"] == 3
    assert len(executed) == 3
    assert all(
        f'INSERT INTO "{scenario.SCENARIO_ID}".observations' in statement
        for statement, _ in executed
    )
    assert not any(
        table in statement
        for statement, _ in executed
        for table in ("incidents", "event_projections", "analysis", "plans")
    )


def test_reconstructed_index_uses_real_parser_matcher_and_publishable_policy():
    anomaly_time = build_rows()[0]["observed_at"]
    result = ReconstructedIndexReplayClient().get_station_index_evidence(
        station_id="86", channel_id="15", pollutant="PM10",
        observed_at=anomaly_time,
    )

    assert result.status == "available"
    evidence = result.evidence
    assert evidence is not None
    assert (evidence.station_id, evidence.monitor_id, evidence.pollutant) == (
        "86", "15", "PM10"
    )
    assert evidence.averaged_concentration == 119.1
    assert evidence.averaging_period_minutes == 1440
    assert evidence.provider_timestamp - timedelta(minutes=1440) < anomaly_time
    assert anomaly_time <= evidence.provider_timestamp
    assert any("RECONSTRUCTED DEMO EVIDENCE" in item for item in evidence.limitations)

    classification = classify_official_pollutant_sub_index(
        pollutant="PM10", pollutant_sub_index=evidence.pollutant_sub_index
    )
    assert classification.classification == "MODERATE"
    qualification = AirPollutionEventQualification(
        qualified=True, path="PATH_A", reason="different_station_corroboration"
    )
    assert publication_policy(
        qualification, classification
    ).publish_to_operational_dashboard


def test_reconstructed_index_keeps_exact_identity_and_window_gates():
    client = ReconstructedIndexReplayClient()
    anomaly_time = build_rows()[0]["observed_at"]

    assert client.get_station_index_evidence(
        station_id="86", channel_id="99", pollutant="PM10",
        observed_at=anomaly_time,
    ).reason == "channel_mismatch"
    assert client.get_station_index_evidence(
        station_id="86", channel_id="15", pollutant="NO2",
        observed_at=anomaly_time,
    ).reason == "pollutant_mismatch"
    assert client.get_station_index_evidence(
        station_id="86", channel_id="15", pollutant="PM10",
        observed_at=anomaly_time - timedelta(days=2),
    ).reason == "timestamp_incompatible"


def test_historical_metar_is_selected_without_live_fallback():
    first, _, metar = build_rows()
    live = Mock()
    writer = Mock()
    stored = {
        **metar,
        "distance_m": 3100.0,
    }
    reader = Mock(return_value=stored)
    service = PersistedFirstWindEvidenceService(
        live, reader=reader, writer=writer,
    )

    selection = service.select_wind_evidence(
        analysis_coordinates=first["payload"]["location"],
        anomaly_observed_at=first["observed_at"],
        maximum_observation_age_seconds=3600,
    )

    evidence = selection.wind_evidence
    assert evidence.provider == "METAR"
    assert evidence.provider_location_id == "LLHA"
    assert evidence.wind_from_direction_deg == 310.0
    assert evidence.wind_speed_mps == 14.816 / 3.6
    assert evidence.wind_observed_at == metar["observed_at"]
    assert "metar_wind" in PERSISTED_WIND_SOURCES
    live.select_wind_evidence.assert_not_called()
    writer.assert_not_called()


def test_scenario_transport_uses_documented_window_and_offline_boundary():
    service = transport_prediction_service()

    assert service is not None
    assert service.configuration.wind_max_age_minutes == 60.0


def test_recorded_model_output_still_passes_real_retrieval_and_grounding():
    analysis, _ = _analysis()
    payload = analysis.model_dump(round_trip=True)
    payload = _replace(payload, "NO2", "PM10")
    payload = _replace(payload, "ppb", "\u00b5g/m\u00b3")
    analysis = type(analysis).model_validate(payload)
    planner = AirPollutionResponsePlanner(llm_service=RecordedPlannerModel())

    result = planner.plan_response(analysis)

    assert result.plan.status == "success"
    assert len(result.plan.actions) == 2
    assert all(item.verified for item in result.plan.protocol_references)
    assert {
        item.document_id for item in result.plan.protocol_references
    } == {"israel-particulate-advisory", "israel-air-monitoring"}


def test_required_display_name_is_explicit():
    assert DISPLAY_NAME == "Israel PM10 Dust Episode — 11 May 2024"
