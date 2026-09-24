"""Contract checks for the opt-in manual Fire pipeline scenarios."""

from datetime import datetime, timedelta, timezone

from ecoguard.analyzers.fire.incident_handler import FireIncidentHandler
from ecoguard.api.fire_manual_test import (
    SCENARIOS,
    SyntheticFirePlanner,
    SyntheticRiskAnalyzer,
    _scenario_signals,
)
from ecoguard.api import fire_manual_test
from ecoguard.api.flood_manual_test import MemoryIncidentStore
from ecoguard.coordinator.agent import coordinate
from ecoguard.coordinator.dispatcher import dispatch_touched
from ecoguard.detectors.fire.satellite import _report


NOW = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)


def _process(scenario: str):
    detector_input = _scenario_signals(scenario, NOW)
    detector_output = [signal for signal in detector_input if _report(signal)]
    incidents = MemoryIncidentStore()
    at = max(signal.observed_at for signal in detector_input) + timedelta(minutes=1)
    coordination = coordinate(detector_output, at=at, incident_store=incidents)
    risk = SyntheticRiskAnalyzer(scenario)
    planner = SyntheticFirePlanner(scenario)
    handler = FireIncidentHandler(
        risk_analyzer=risk,
        planner=planner,
        clock=lambda: at,
    )
    processing = dispatch_touched(
        coordination.touched_ids,
        registry={("fire", "emergency"): handler},
        incident_reader=incidents.incident_by_id,
        at=at,
    )
    return detector_input, detector_output, incidents, coordination, risk, planner, processing


def test_every_documented_scenario_has_a_fixture():
    for scenario in SCENARIOS:
        assert _scenario_signals(scenario, NOW)


def test_routine_persistent_source_is_filtered_but_novel_and_unknown_are_kept():
    routine = _scenario_signals("routine_suppressed", NOW)[0]
    novel = _scenario_signals("persistent_novel", NOW)[0]
    unknown = _scenario_signals("baseline_missing", NOW)[0]

    assert _report(routine) is False
    assert _report(novel) is True
    assert _report(unknown) is True


def test_confirmed_fire_keeps_noise_in_input_but_not_detector_output():
    detector_input, detector_output, _, coordination, _, planner, processing = _process(
        "confirmed_fire"
    )

    assert len(detector_input) == 2
    assert len(detector_output) == 1
    assert len(coordination.created) == 1
    assert processing[0].status == "success"
    assert processing[0].risk_status == "success"
    assert processing[0].planner_status == "success"
    assert len(planner.calls) == 1
    assert planner.calls[0].risk_context["risk_semantics"] == (
        "detected_event_operational_risk"
    )


def test_adjacent_observations_deduplicate_and_distant_observations_do_not():
    *_, adjacent_coordination, _risk, _planner, adjacent_processing = _process(
        "adjacent_deduplicated"
    )
    *_, separate_coordination, _risk, _planner, separate_processing = _process(
        "separate_fires"
    )

    assert len(adjacent_coordination.created) == 1
    assert len(adjacent_coordination.updated) == 1
    assert len(adjacent_processing) == 1
    assert len(separate_coordination.created) == 2
    assert len(separate_processing) == 2


def test_risk_failure_skips_planner_and_allocation_handoff():
    *_, planner, processing = _process("risk_failure")

    assert planner.calls == []
    assert processing[0].status == "partial"
    assert processing[0].failure_stage == "risk_analysis"
    assert processing[0].planner_status == "skipped"
    assert processing[0].requires_resource_allocation is False


def test_invalid_risk_semantics_is_rejected_before_planner():
    *_, planner, processing = _process("invalid_risk_semantics")

    assert planner.calls == []
    assert processing[0].failure_stage == "planning_input"
    assert processing[0].failure_reason == "risk_analysis_unavailable"
    assert processing[0].requires_resource_allocation is False


def test_planner_failure_does_not_request_allocation():
    *_, planner, processing = _process("planner_failure")

    assert len(planner.calls) == 1
    assert processing[0].status == "partial"
    assert processing[0].planner_status == "failed"
    assert processing[0].requires_resource_allocation is False


def test_missing_location_fails_before_risk_analysis():
    *_, risk, planner, processing = _process("missing_location")

    assert risk.calls == []
    assert planner.calls == []
    assert processing[0].status == "failed"
    assert processing[0].failure_stage == "adaptation"


def test_fire_quiet_period_is_strictly_more_than_six_hours():
    _, _, incidents, coordination, _, _, _ = _process("ended")
    incident = incidents.incident_by_id(coordination.touched_ids[0])

    exact = coordinate(
        [], at=incident["last_signal_at"] + timedelta(hours=6),
        incident_store=incidents,
    )
    after = coordinate(
        [], at=incident["last_signal_at"] + timedelta(hours=6, seconds=1),
        incident_store=incidents,
    )

    assert exact.closed == []
    assert after.closed == [incident["id"]]


def test_manual_endpoint_runs_full_in_memory_flow_without_db_or_model_calls(
    monkeypatch, capsys
):
    class NoExternalAllocator:
        def __init__(self, **_):
            self.last_batch_input = None

        def allocate_processing_results(self, processing):
            self.last_batch_input = [
                {
                    "incident_id": item.incident_id,
                    "hazard": item.hazard,
                    "response_plan": item.planner_result,
                }
                for item in processing
                if item.requires_resource_allocation
            ]
            return {}

        def release_incident(self, *_args, **_kwargs):
            return []

    monkeypatch.setenv("ECOGUARD_MANUAL_FIRE_TEST", "1")
    monkeypatch.setattr(fire_manual_test, "RecordingAllocator", NoExternalAllocator)
    monkeypatch.setattr(fire_manual_test, "MapboxClient", object)

    report = fire_manual_test.run_scenario("confirmed_fire")

    assert report["safety"]["database_writes"] == 0
    assert report["safety"]["claude_calls"] == 0
    assert len(report["detector_input"]) == 2
    assert len(report["detector_output"]) == 1
    assert report["response_planner_input"][0]["hazard_type"] == "fire"
    assert report["resource_allocator_input"][0]["hazard"] == "fire"
    assert len(report["api_events_response"]["events"]) == 1
    assert report["api_events_response"]["events"][0]["type"] == "fire"
    capsys.readouterr()
