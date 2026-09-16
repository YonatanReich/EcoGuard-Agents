"""Contract tests for the current flood detection agent."""

from datetime import datetime, timezone

from ecoguard.detectors.flood.detection_agent import FloodDetectionAgent
from ecoguard.detectors.flood.rules import RAIN_GAUGE_SOURCE


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0040-c0012"


def test_agent_evaluates_an_urban_rain_threshold_crossing():
    agent = FloodDetectionAgent()
    observations = [
        {
            "id": 9,
            "source": RAIN_GAUGE_SOURCE,
            "cell_id": CELL,
            "observed_at": NOW,
            "payload": {
                "stations": [
                    {
                        "source_station_id": 205,
                        "rainfall_mm": 9.0,
                        "latitude": 32.0,
                        "longitude": 34.8,
                    }
                ]
            },
        }
    ]
    context = {
        "cell_id": CELL,
        "latitude": 32.0,
        "longitude": 34.8,
        "built_up_fraction": 0.8,
        "slope_deg": 0.0,
        "distance_to_stream_m": 1000.0,
    }

    evaluation = agent.evaluate(
        cell_id=CELL,
        observations=observations,
        context=context,
        baselines={},
    )

    assert len(evaluation.candidates) == 1
    assert evaluation.candidates[0].trigger == "urban_rain_10m"
    assert evaluation.candidates[0].severity_hint == "moderate"
    assert evaluation.resolutions == []


def test_agent_exposes_the_required_observation_lookback():
    assert FloodDetectionAgent().lookback.total_seconds() >= 24 * 60 * 60


def test_agent_does_not_reopen_an_event_that_is_already_active():
    agent = FloodDetectionAgent()
    observations = [
        {
            "source": RAIN_GAUGE_SOURCE,
            "cell_id": CELL,
            "observed_at": NOW,
            "payload": {
                "stations": [
                    {
                        "source_station_id": 205,
                        "rainfall_mm": 9.0,
                        "latitude": 32.0,
                        "longitude": 34.8,
                    }
                ]
            },
        }
    ]
    context = {
        "cell_id": CELL,
        "latitude": 32.0,
        "longitude": 34.8,
        "built_up_fraction": 0.8,
        "distance_to_stream_m": 1000.0,
    }
    opened = agent.evaluate(
        cell_id=CELL,
        observations=observations,
        context=context,
        baselines={},
    ).candidates[0]

    evaluation = agent.evaluate(
        cell_id=CELL,
        observations=observations,
        context=context,
        baselines={},
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
