"""Shared scheduled detector/coordinator batch integration tests."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ecoguard.shared.signals import (
    AIR_POLLUTION,
    EARTHQUAKE,
    FIRE,
    FLOOD,
    HIGH,
    CellSignal,
)


@pytest.fixture(autouse=True)
def _empty_flood_detector(monkeypatch):
    """Keep scheduler tests isolated unless they explicitly provide a batch."""
    from ecoguard.detectors.flood import observation_processing

    monkeypatch.setattr(
        observation_processing,
        "detect_new",
        lambda: [],
    )

    # The media lane is stubbed for the same reason as the flood detector: these
    # tests assert what one tick hands the coordinator, and the real lane reads
    # whatever news happens to be in the database and spends a model call
    # classifying it. Its own tests cover it.
    from ecoguard.detectors.text import classifier, run as text_run

    monkeypatch.setattr(classifier, "classify_new_text", lambda **kwargs: None)
    monkeypatch.setattr(text_run, "run_text_triage", lambda **kwargs: None)


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


def test_structured_signals_go_straight_to_the_coordinator(monkeypatch):
    """No enrichment step sits between a structured detector and the coordinator.

    detect_and_coordinate hands detector output to the coordinator unchanged;
    Telegram/RSS text goes through the separate process_text_events lane, and
    the old Telegram evidence enricher this used to guard against is gone.
    """
    from ecoguard import scheduler as shared_runtime
    from ecoguard.coordinator import agent
    from ecoguard.detectors.air_pollution import observation_processing
    from ecoguard.detectors.fire import satellite, weather

    fire = _fire_signal()
    calls = []
    monkeypatch.setattr(satellite, "detect_new", lambda: [fire])
    monkeypatch.setattr(weather, "detect_new", lambda: [])
    monkeypatch.setattr(observation_processing, "detect_new", lambda: [])
    monkeypatch.setattr(
        agent,
        "run",
        lambda signals: calls.append(("coordinate", list(signals))),
    )

    shared_runtime.detect_and_coordinate()

    assert calls == [("coordinate", [fire])]


def test_text_processing_job_is_registered_exactly_once():
    from ecoguard.scheduler import scheduler

    jobs = [job for job in scheduler.get_jobs() if job.id == "process_text_events"]

    assert len(jobs) == 1
    assert jobs[0].trigger.interval.total_seconds() == 3 * 60
    assert jobs[0].max_instances == 1
    assert jobs[0].coalesce is True


def test_text_processing_runs_classifier_then_triage(monkeypatch):
    from contextlib import contextmanager

    from ecoguard import scheduler as shared_runtime
    from ecoguard.detectors.text import classifier, run

    calls = []

    @contextmanager
    def acquired(_name):
        yield True

    monkeypatch.setattr(shared_runtime, "single_flight", acquired)
    monkeypatch.setattr(
        classifier, "classify_new_text",
        lambda: calls.append("classify") or {"messages": 1},
    )
    monkeypatch.setattr(
        run, "run_text_triage",
        lambda: calls.append("triage") or {"events": 1},
    )

    result = shared_runtime.process_text_events()

    assert calls == ["classify", "triage"]
    assert result == {
        "classification": {"messages": 1},
        "triage": {"events": 1},
    }


def test_text_classification_failure_is_isolated_and_triage_still_runs(monkeypatch):
    from contextlib import contextmanager

    from ecoguard import scheduler as shared_runtime
    from ecoguard.detectors.text import classifier, run

    calls = []

    @contextmanager
    def acquired(_name):
        yield True

    monkeypatch.setattr(shared_runtime, "single_flight", acquired)
    monkeypatch.setattr(
        classifier, "classify_new_text",
        lambda: (_ for _ in ()).throw(RuntimeError("model unavailable")),
    )
    monkeypatch.setattr(
        run, "run_text_triage",
        lambda: calls.append("triage") or {"events": 0},
    )

    result = shared_runtime.process_text_events()

    assert calls == ["triage"]
    assert result["classification"] is None
    assert result["triage"] == {"events": 0}


def test_text_triage_failure_isolated_from_the_scheduler(monkeypatch):
    from contextlib import contextmanager

    from ecoguard import scheduler as shared_runtime
    from ecoguard.detectors.text import classifier, run

    @contextmanager
    def acquired(_name):
        yield True

    monkeypatch.setattr(shared_runtime, "single_flight", acquired)
    monkeypatch.setattr(classifier, "classify_new_text", lambda: {"messages": 0})
    monkeypatch.setattr(
        run, "run_text_triage",
        lambda: (_ for _ in ()).throw(RuntimeError("coordinator unavailable")),
    )

    result = shared_runtime.process_text_events()

    assert result == {"classification": {"messages": 0}, "triage": None}


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
    assert jobs[0].trigger.interval.total_seconds() == 10 * 60
    assert jobs[0].max_instances == 1
    assert jobs[0].coalesce is True


def test_flood_collection_runs_every_ten_minutes_without_a_dedicated_detector_job():
    from ecoguard.collection.flood.hydrometric_observations import SOURCE
    from ecoguard.scheduler import scheduler

    collector = scheduler.get_job(f"collect_{SOURCE}")
    assert collector is not None
    assert collector.trigger.interval.total_seconds() == 10 * 60
    assert scheduler.get_job("detect_flood_and_coordinate") is None


def test_flood_signal_uses_the_same_coordinator_batch(monkeypatch):
    from ecoguard import scheduler as shared_runtime
    from ecoguard.coordinator import agent, dispatcher, event_projection
    from ecoguard.detectors.air_pollution import observation_processing as air
    from ecoguard.detectors.fire import satellite, weather
    from ecoguard.detectors.flood import observation_processing

    at = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
    signal = CellSignal(
        cell_id="ISR-001-003",
        observed_at=at,
        hazard=FLOOD,
        variable="discharge",
        value=35.0,
        unit="m3/s",
        source="water_authority_hydrometric_observations",
        rarity=None,
        direction=HIGH,
    )
    received = []
    monkeypatch.setattr(satellite, "detect_new", lambda: [])
    monkeypatch.setattr(weather, "detect_new", lambda: [])
    monkeypatch.setattr(air, "detect_new", lambda: [])
    monkeypatch.setattr(
        observation_processing,
        "detect_new",
        lambda: [signal],
    )
    monkeypatch.setattr(
        agent,
        "run",
        lambda signals: received.extend(signals) or agent.CoordinationResult(),
    )
    monkeypatch.setattr(dispatcher, "dispatch_touched", lambda identifiers: [])
    monkeypatch.setattr(event_projection, "project_processing_results", lambda _: None)

    shared_runtime.detect_and_coordinate()

    assert received == [signal]


def test_earthquake_signal_uses_the_same_coordinator_batch(monkeypatch):
    from ecoguard import scheduler as shared_runtime
    from ecoguard.coordinator import agent, dispatcher, event_projection
    from ecoguard.detectors.air_pollution import observation_processing as air
    from ecoguard.detectors.earthquake import observation_processing as earthquake
    from ecoguard.detectors.fire import satellite, weather

    signal = CellSignal(
        cell_id="ISR-001-004",
        observed_at=datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc),
        hazard=EARTHQUAKE,
        variable="magnitude",
        value=4.2,
        unit="Mw",
        source="gsi_earthquake",
        rarity=None,
        direction=HIGH,
    )
    received = []
    monkeypatch.setattr(satellite, "detect_new", lambda: [])
    monkeypatch.setattr(weather, "detect_new", lambda: [])
    monkeypatch.setattr(air, "detect_new", lambda: [])
    monkeypatch.setattr(earthquake, "detect_new", lambda: [signal])
    monkeypatch.setattr(
        agent,
        "run",
        lambda signals: received.extend(signals) or agent.CoordinationResult(),
    )
    monkeypatch.setattr(dispatcher, "dispatch_touched", lambda identifiers: [])
    monkeypatch.setattr(event_projection, "project_processing_results", lambda _: None)

    shared_runtime.detect_and_coordinate()

    assert received == [signal]


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
    earthquake = SimpleNamespace(
        incident_id="INC-EQ-1",
        hazard="earthquake",
        route="emergency",
        requested_at=requested_at,
        planner_result={
            "metadata": {"planning_status": "success"},
            "hazard_type": "earthquake",
        },
        resource_allocation_result=None,
    )

    class RecordingAllocator:
        def __init__(self):
            self.calls = []

        def allocate_processing_results(self, results):
            self.calls.append(results)
            return {"delegated": True}

    allocator = RecordingAllocator()
    monkeypatch.setattr(shared_runtime, "resource_allocator", allocator)

    allocations = shared_runtime.allocate_resources(
        [fire_one, advisory, fire_two, earthquake]
    )

    # The scheduler is now a delegation boundary: one call, every result handed
    # over unchanged, and whatever the allocator returns passed straight back.
    #
    # This test used to assert the requests the scheduler built itself -- the
    # eligibility filter, the per-hazard request shape and the earthquake
    # policy tag. Those did not disappear; they moved into
    # ResourceAllocationAgent.allocate_processing_results, where the hazard
    # branches live, and test_batch_allocation covers them there. Asserting
    # them here as well would be asserting the allocator through a fake that
    # does not implement it.
    assert len(allocator.calls) == 1
    assert allocator.calls[0] == [fire_one, advisory, fire_two, earthquake]
    assert allocations == {"delegated": True}


def test_scheduler_passes_flood_result_unchanged_to_resource_allocator(monkeypatch):
    from ecoguard import scheduler as shared_runtime

    requested_at = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    flood = SimpleNamespace(
        incident_id="INC-FLOOD-1",
        hazard="flood",
        route="emergency",
        requested_at=requested_at,
        planner_result=None,
        resource_allocation_result=None,
    )

    class RecordingAllocator:
        def __init__(self):
            self.results = None

        def allocate_processing_results(self, results):
            self.results = results
            return {"INC-FLOOD-1": {"status": "fulfilled"}}

    allocator = RecordingAllocator()
    monkeypatch.setattr(shared_runtime, "resource_allocator", allocator)

    shared_runtime.allocate_resources([flood])

    assert allocator.results == [flood]


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


def test_advisory_plans_publish_before_the_allocator_runs(monkeypatch):
    """The two planning lines: advisory straight out, emergency via allocation."""
    from ecoguard import scheduler as shared_runtime
    from ecoguard.coordinator import agent, dispatcher, event_projection
    from ecoguard.detectors.air_pollution import observation_processing
    from ecoguard.detectors.fire import satellite, weather

    advisory = SimpleNamespace(incident_id="INC-AIR", route="non_emergency")
    emergency = SimpleNamespace(incident_id="INC-FIRE", route="emergency")
    order = []

    monkeypatch.setattr(satellite, "detect_new", lambda: [])
    monkeypatch.setattr(weather, "detect_new", lambda: [])
    monkeypatch.setattr(observation_processing, "detect_new", lambda: [])
    monkeypatch.setattr(
        agent, "run", lambda signals: agent.CoordinationResult(created=["INC-1"])
    )
    monkeypatch.setattr(
        dispatcher, "dispatch_touched", lambda identifiers: [advisory, emergency]
    )
    monkeypatch.setattr(
        shared_runtime,
        "allocate_resources",
        lambda results: order.append(("allocate", [r.incident_id for r in results])),
    )
    monkeypatch.setattr(
        event_projection,
        "project_processing_results",
        lambda results: order.append(("publish", [r.incident_id for r in results])),
    )

    shared_runtime.detect_and_coordinate()

    assert order == [
        ("publish", ["INC-AIR"]),
        ("allocate", ["INC-FIRE"]),
        ("publish", ["INC-FIRE"]),
    ]
