"""Contract tests for the pure hydrometric detection agent."""

from datetime import datetime, timedelta, timezone

from ecoguard.detectors.flood.detection_agent import FloodDetectionAgent


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)


def test_agent_accepts_a_fresh_realtime_observation():
    observation = {
        "observed_at": NOW - timedelta(minutes=10),
        "ingested_at": NOW,
    }

    assert FloodDetectionAgent().accepts_pending(observation) is True


def test_agent_rejects_a_delayed_backfill_as_realtime_input():
    observation = {
        "observed_at": NOW - timedelta(days=2),
        "ingested_at": NOW,
    }

    assert FloodDetectionAgent().accepts_pending(observation) is False


def test_agent_rejects_an_implausibly_future_observation():
    observation = {
        "observed_at": NOW + timedelta(minutes=20),
        "ingested_at": NOW,
    }

    assert FloodDetectionAgent().accepts_pending(observation) is False
