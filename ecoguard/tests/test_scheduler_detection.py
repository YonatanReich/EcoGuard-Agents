"""Shared scheduled detector/coordinator batch integration tests."""

from datetime import datetime, timezone

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
