"""Shared scheduled detector/coordinator batch integration tests."""

from datetime import datetime, timezone
from types import SimpleNamespace

from ecoguard.shared.signals import AIR_POLLUTION, FIRE, HIGH, CellSignal


def _fire_signal() -> CellSignal:
    return CellSignal(
        cell_id="ISR-001-001",
        observed_at=datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc),
        hazard=FIRE,
        variable="frp",
        value=20.0,
        unit="MW",
        source="firms",
        rarity=1.0,
        direction=HIGH,
    )


def _air_pollution_signal() -> CellSignal:
    return CellSignal(
        cell_id="ISR-001-002",
        observed_at=datetime(2026, 9, 16, 10, 5, tzinfo=timezone.utc),
        hazard=AIR_POLLUTION,
        variable="NO2",
        value=21.0,
        unit="ppb",
        source="israel_ministry_environment_air_monitoring",
        rarity=None,
        direction=HIGH,
        confidence=None,
        severity=None,
    )


def test_fire_and_air_pollution_share_one_coordinator_batch(monkeypatch):
    from ecoguard import scheduler as shared_runtime
    from ecoguard.coordinator import agent
    from ecoguard.detectors.air_pollution import observation_processing
    from ecoguard.detectors.fire import satellite, weather

    fire = _fire_signal()
    pollution = _air_pollution_signal()
    batches = []
    monkeypatch.setattr(satellite, "detect_new", lambda: [fire])
    monkeypatch.setattr(weather, "detect_new", lambda: [])
    monkeypatch.setattr(observation_processing, "detect_new", lambda: [pollution])
    monkeypatch.setattr(agent, "run", lambda signals: batches.append(signals))

    shared_runtime.detect_and_coordinate()

    assert batches == [[fire, pollution]]


def test_air_pollution_failure_does_not_suppress_fire_signals(monkeypatch):
    from ecoguard import scheduler as shared_runtime
    from ecoguard.coordinator import agent
    from ecoguard.detectors.air_pollution import observation_processing
    from ecoguard.detectors.fire import satellite, weather

    fire = _fire_signal()
    received = []
    monkeypatch.setattr(satellite, "detect_new", lambda: [fire])
    monkeypatch.setattr(weather, "detect_new", lambda: [])
    monkeypatch.setattr(
        observation_processing,
        "detect_new",
        lambda: (_ for _ in ()).throw(RuntimeError("air pollution failed")),
    )
    monkeypatch.setattr(agent, "run", lambda signals: received.extend(signals))

    shared_runtime.detect_and_coordinate()

    assert received == [fire]


def test_shared_detection_job_is_registered_exactly_once():
    from ecoguard.scheduler import scheduler

    jobs = [job for job in scheduler.get_jobs() if job.id == "detect_and_coordinate"]

    assert len(jobs) == 1
    assert jobs[0].trigger.interval.total_seconds() == 30 * 60
    assert jobs[0].max_instances == 1
    assert jobs[0].coalesce is True


def test_scheduler_dispatches_only_coordinator_touched_incidents(monkeypatch):
    from ecoguard import scheduler as shared_runtime
    from ecoguard.coordinator import agent, dispatcher, event_projection
    from ecoguard.detectors.air_pollution import observation_processing
    from ecoguard.detectors.fire import satellite, weather

    coordination = agent.CoordinationResult(
        created=["INC-1"],
        updated=["INC-2", "INC-1"],
    )
    dispatched = []
    projected = []
    monkeypatch.setattr(satellite, "detect_new", lambda: [])
    monkeypatch.setattr(weather, "detect_new", lambda: [])
    monkeypatch.setattr(observation_processing, "detect_new", lambda: [])
    monkeypatch.setattr(agent, "run", lambda signals: coordination)
    monkeypatch.setattr(
        dispatcher,
        "dispatch_touched",
        lambda identifiers: dispatched.extend(identifiers) or ["processed"],
    )
    monkeypatch.setattr(
        event_projection,
        "project_processing_results",
        lambda results: projected.extend(results),
    )

    assert shared_runtime.detect_and_coordinate() == ["processed"]
    assert dispatched == ["INC-1", "INC-2"]
    assert projected == ["processed"]


def test_scheduler_projection_failure_does_not_erase_processing_results(monkeypatch):
    from ecoguard import scheduler as shared_runtime
    from ecoguard.coordinator import agent, dispatcher, event_projection
    from ecoguard.detectors.air_pollution import observation_processing
    from ecoguard.detectors.fire import satellite, weather

    monkeypatch.setattr(satellite, "detect_new", lambda: [])
    monkeypatch.setattr(weather, "detect_new", lambda: [])
    monkeypatch.setattr(observation_processing, "detect_new", lambda: [])
    monkeypatch.setattr(
        agent,
        "run",
        lambda signals: agent.CoordinationResult(created=["INC-1"]),
    )
    monkeypatch.setattr(
        dispatcher,
        "dispatch_touched",
        lambda identifiers: ["processed"],
    )

    def fail_projection(results):
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(
        event_projection,
        "project_processing_results",
        fail_projection,
    )

    assert shared_runtime.detect_and_coordinate() == ["processed"]


def test_scheduler_allocates_all_eligible_fire_plans_in_one_batch(monkeypatch):
    from ecoguard import scheduler as shared_runtime

    requested_at = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
    fire_one = SimpleNamespace(
        incident_id="INC-FIRE-1",
        hazard="fire",
        route="emergency",
        requested_at=requested_at,
        planner_result={"event_id": "PLAN-1"},
        resource_allocation_result=None,
    )
    fire_two = SimpleNamespace(
        incident_id="INC-FIRE-2",
        hazard="fire",
        route="emergency",
        requested_at=requested_at,
        planner_result={"event_id": "PLAN-2"},
        resource_allocation_result=None,
    )
    advisory = SimpleNamespace(
        incident_id="INC-AIR-1",
        hazard="air_pollution",
        route="advisory",
        requested_at=requested_at,
        planner_result={"event_id": "PLAN-3"},
        resource_allocation_result=None,
    )

    class RecordingAllocator:
        def __init__(self):
            self.calls = []

        def allocate_batch(self, requests):
            self.calls.append(requests)
            return [
                {"incident_id": request["incident_id"], "status": "allocated"}
                for request in requests
            ]

    allocator = RecordingAllocator()
    monkeypatch.setattr(shared_runtime, "resource_allocator", allocator)

    allocations = shared_runtime.allocate_resources(
        [fire_one, advisory, fire_two]
    )

    assert len(allocator.calls) == 1
    assert [
        request["incident_id"] for request in allocator.calls[0]
    ] == ["INC-FIRE-1", "INC-FIRE-2"]
    assert allocator.calls[0][0]["response_plan"] == {"event_id": "PLAN-1"}
    assert fire_one.resource_allocation_result == {
        "incident_id": "INC-FIRE-1",
        "status": "allocated",
    }
    assert fire_two.resource_allocation_result == {
        "incident_id": "INC-FIRE-2",
        "status": "allocated",
    }
    assert advisory.resource_allocation_result is None
    assert set(allocations) == {"INC-FIRE-1", "INC-FIRE-2"}


def test_scheduler_allocation_failure_does_not_block_projection(monkeypatch):
    from ecoguard import scheduler as shared_runtime
    from ecoguard.coordinator import agent, dispatcher, event_projection
    from ecoguard.detectors.air_pollution import observation_processing
    from ecoguard.detectors.fire import satellite, weather

    processing_results = ["planned"]
    projected = []
    monkeypatch.setattr(satellite, "detect_new", lambda: [])
    monkeypatch.setattr(weather, "detect_new", lambda: [])
    monkeypatch.setattr(observation_processing, "detect_new", lambda: [])
    monkeypatch.setattr(
        agent,
        "run",
        lambda signals: agent.CoordinationResult(created=["INC-1"]),
    )
    monkeypatch.setattr(
        dispatcher,
        "dispatch_touched",
        lambda identifiers: processing_results,
    )
    monkeypatch.setattr(
        shared_runtime,
        "allocate_resources",
        lambda results: (_ for _ in ()).throw(RuntimeError("allocator failed")),
    )
    monkeypatch.setattr(
        event_projection,
        "project_processing_results",
        lambda results: projected.extend(results),
    )

    assert shared_runtime.detect_and_coordinate() == processing_results
    assert projected == processing_results
