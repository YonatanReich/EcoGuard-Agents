"""Focused tests for flood threshold and persistence rules."""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.detectors.flood.station_rules import (
    HYDROMETRIC_SOURCE,
    alert_level,
    evaluate_cell,
    severity_level,
)


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0040-c0012"
THRESHOLDS = (10.0, 20.0, 30.0, 40.0, 50.0, 60.0)


def _observation(
    at: datetime,
    discharge: float,
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


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (0, "none"),
        (1, "none"),
        (2, "monitoring"),
        (3, "active"),
        (4, "severe"),
        (5, "emergency"),
        (6, "emergency"),
    ],
)
def test_operational_alert_level_mapping(severity, expected):
    assert alert_level(severity) == expected


def test_two_q10_readings_emit_one_shared_signal():
    signals = evaluate_cell(
        CELL,
        [
            _observation(NOW - timedelta(minutes=10), 31.0),
            _observation(NOW, 45.0),
        ],
        stream_ids={50: 701},
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.value == 45.0
    assert signal.evidence["severity_level"] == 4
    assert signal.evidence["alert_level"] == "severe"
    assert signal.evidence["stream_id"] == 701


def test_q5_pair_is_monitoring_only_and_emits_no_signal():
    signals = evaluate_cell(
        CELL,
        [
            _observation(NOW - timedelta(minutes=10), 21.0),
            _observation(NOW, 22.0),
        ],
    )

    assert signals == []


def test_one_q10_reading_is_not_enough():
    signals = evaluate_cell(
        CELL,
        [
            _observation(NOW - timedelta(minutes=10), 29.0),
            _observation(NOW, 31.0),
        ],
    )

    assert signals == []


def test_large_sample_gap_breaks_persistence():
    signals = evaluate_cell(
        CELL,
        [
            _observation(NOW - timedelta(hours=1), 31.0),
            _observation(NOW, 32.0),
        ],
    )

    assert signals == []


def test_missing_threshold_station_is_ignored_entirely():
    signals = evaluate_cell(
        CELL,
        [
            _observation(
                NOW - timedelta(minutes=10),
                100.0,
                status="missing_thresholds",
            ),
            _observation(NOW, 100.0, status="missing_thresholds"),
        ],
    )

    assert signals == []


def test_only_new_target_timestamp_emits_a_signal():
    earlier = NOW - timedelta(minutes=20)
    current = NOW - timedelta(minutes=10)
    signals = evaluate_cell(
        CELL,
        [
            _observation(earlier, 31.0),
            _observation(current, 32.0),
            _observation(NOW, 33.0),
        ],
        target_observed_at={NOW},
    )

    assert [signal.observed_at for signal in signals] == [NOW]
