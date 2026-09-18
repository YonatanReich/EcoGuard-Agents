"""Contract tests for the minimal hydrometric flood detection agent."""

from datetime import datetime, timedelta, timezone

from ecoguard.detectors.flood.detection_agent import FloodDetectionAgent
from ecoguard.detectors.flood.station_rules import HYDROMETRIC_SOURCE


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0040-c0012"


def _observation(at: datetime, discharge: float) -> dict:
    return {
        "source": HYDROMETRIC_SOURCE,
        "cell_id": CELL,
        "observed_at": at,
        "payload": {
            "stations": [
                {
                    "source_station_id": 50,
                    "discharge_m3s": discharge,
                    "latitude": 32.0,
                    "longitude": 34.8,
                    "flow_threshold_status": "complete_thresholds",
                    "flow_threshold_2y_m3s": 10.0,
                    "flow_threshold_5y_m3s": 20.0,
                    "flow_threshold_10y_m3s": 30.0,
                    "flow_threshold_20y_m3s": 40.0,
                    "flow_threshold_50y_m3s": 50.0,
                    "flow_threshold_100y_m3s": 60.0,
                }
            ]
        },
    }


def test_agent_opens_only_after_two_consecutive_q5_readings():
    agent = FloodDetectionAgent()
    observations = [
        _observation(NOW - timedelta(minutes=10), 21.0),
        _observation(NOW, 22.0),
    ]

    evaluation = agent.evaluate(cell_id=CELL, observations=observations)

    assert len(evaluation.candidates) == 1
    assert evaluation.candidates[0].evidence["severity_level"] == 2
    assert evaluation.resolutions == []


def test_agent_rejects_a_delayed_backfill_as_a_realtime_signal():
    observation = {
        "observed_at": NOW - timedelta(days=2),
        "ingested_at": NOW,
    }

    assert FloodDetectionAgent().accepts_pending(observation) is False


def test_agent_does_not_reopen_an_event_that_is_already_active():
    agent = FloodDetectionAgent()
    observations = [
        _observation(NOW - timedelta(minutes=10), 21.0),
        _observation(NOW, 22.0),
    ]
    opened = agent.evaluate(
        cell_id=CELL,
        observations=observations,
    ).candidates[0]

    evaluation = agent.evaluate(
        cell_id=CELL,
        observations=observations,
        active_events=[
            {
                "event_key": opened.event_key,
                "candidate_key": opened.candidate_key,
                "cell_id": CELL,
                "opened_at": opened.observed_at,
                "trigger": opened.trigger,
                "evidence": opened.evidence,
            }
        ],
    )

    assert evaluation.candidates == []
    assert evaluation.resolutions == []
