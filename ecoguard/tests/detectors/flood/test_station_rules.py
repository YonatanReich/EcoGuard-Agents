"""Focused tests for threshold, persistence and hysteresis rules."""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.detectors.flood.station_rules import (
    HYDROMETRIC_SOURCE,
    evaluate_cell,
    evaluate_resolutions,
    severity_level,
)


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0040-c0012"
THRESHOLDS = (10.0, 20.0, 30.0, 40.0, 50.0, 60.0)


def _observation(
    at: datetime,
    discharge: float | None,
    *,
    status: str = "complete_thresholds",
) -> dict:
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
                    "flow_threshold_status": status,
                    **{
                        f"flow_threshold_{period}y_m3s": threshold
                        for period, threshold in zip(
                            (2, 5, 10, 20, 50, 100), THRESHOLDS
                        )
                    },
                }
            ]
        },
    }


@pytest.mark.parametrize(
    ("discharge", "expected"),
    [
        (9.9, 0),
        (10.0, 1),
        (20.0, 2),
        (30.0, 3),
        (40.0, 4),
        (50.0, 5),
        (60.0, 6),
        (100.0, 6),
    ],
)
def test_severity_level_uses_all_six_thresholds(discharge, expected):
    assert severity_level(discharge, THRESHOLDS) == expected


def test_q2_is_monitoring_only_and_does_not_open_an_alert():
    observations = [
        _observation(NOW - timedelta(minutes=10), 11.0),
        _observation(NOW, 12.0),
    ]

    assert evaluate_cell(CELL, observations) == []


def test_two_q5_readings_open_with_the_current_readings_severity():
    observations = [
        _observation(NOW - timedelta(minutes=10), 21.0),
        _observation(NOW, 35.0),
    ]

    candidate = evaluate_cell(CELL, observations)[0]

    assert candidate.evidence["severity_level"] == 3
    assert candidate.evidence["previous_severity_level"] == 2
    assert candidate.evidence["current_discharge"] == 35.0


def test_one_reading_above_q5_is_not_enough():
    observations = [
        _observation(NOW - timedelta(minutes=10), 19.0),
        _observation(NOW, 21.0),
    ]

    assert evaluate_cell(CELL, observations) == []


def test_large_sample_gap_breaks_persistence():
    observations = [
        _observation(NOW - timedelta(hours=1), 21.0),
        _observation(NOW, 22.0),
    ]

    assert evaluate_cell(CELL, observations) == []


def test_missing_threshold_station_cannot_open_an_alert():
    observations = [
        _observation(
            NOW - timedelta(minutes=10),
            100.0,
            status="missing_thresholds",
        ),
        _observation(NOW, 100.0, status="missing_thresholds"),
    ]

    assert evaluate_cell(CELL, observations) == []


def _active_event() -> dict:
    return {
        "event_key": f"flood:gauge:{CELL}:50",
        "candidate_key": "candidate-1",
        "cell_id": CELL,
        "opened_at": NOW - timedelta(hours=1),
        "trigger": "gauge_discharge_threshold",
        "evidence": {"station_id": 50},
    }


def test_two_readings_below_80_percent_of_q5_resolve():
    observations = [
        _observation(NOW - timedelta(minutes=10), 15.9),
        _observation(NOW, 15.0),
    ]

    resolution = evaluate_resolutions(observations, [_active_event()])[0]

    assert resolution.reason == "discharge_below_hysteresis_threshold"
    assert resolution.evidence["exit_threshold_m3s"] == 16.0


def test_reading_on_hysteresis_boundary_does_not_resolve():
    observations = [
        _observation(NOW - timedelta(minutes=10), 15.0),
        _observation(NOW, 16.0),
    ]

    assert evaluate_resolutions(observations, [_active_event()]) == []


def test_one_low_reading_does_not_resolve():
    observations = [_observation(NOW, 15.0)]

    assert evaluate_resolutions(observations, [_active_event()]) == []
