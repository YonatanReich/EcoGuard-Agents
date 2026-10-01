"""Focused tests for flood threshold and persistence rules."""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.detectors.flood.station_rules import (
    FloodPolicy,
    HYDROMETRIC_SOURCE,
    alert_level,
    evaluate_cell,
    operational_severity_level,
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
    flow_regime: str | None = "ephemeral",
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
                    "operational_flow_regime": flow_regime,
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
    ("official_level", "expected"),
    [(0, 3), (1, 3), (2, 4), (3, 5), (4, 6), (5, 6), (6, 6)],
)
def test_confirmed_event_maps_to_existing_operational_scale(
    official_level, expected
):
    assert operational_severity_level(official_level) == expected


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


def test_two_ephemeral_readings_at_one_m3s_emit_one_shared_signal():
    signals = evaluate_cell(
        CELL,
        [
            _observation(NOW - timedelta(minutes=10), 1.0),
            _observation(NOW, 1.4),
        ],
        stream_ids={50: 701},
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.value == 1.4
    assert signal.evidence["detection_rule_version"] == 2
    assert signal.evidence["operational_flow_regime"] == "ephemeral"
    assert signal.evidence["alert_threshold_m3s"] == 1.0
    assert signal.evidence["severity_level"] == 3
    assert signal.evidence["return_period_years"] is None
    assert signal.evidence["alert_level"] == "active"
    assert signal.evidence["stream_id"] == 701


def test_ephemeral_pair_with_one_reading_below_one_m3s_emits_no_signal():
    signals = evaluate_cell(
        CELL,
        [
            _observation(NOW - timedelta(minutes=10), 0.9),
            _observation(NOW, 1.2),
        ],
    )

    assert signals == []


def test_flowing_baseline_requires_two_q2_readings():
    signals = evaluate_cell(
        CELL,
        [
            _observation(
                NOW - timedelta(minutes=10), 10.0, flow_regime="flowing_baseline"
            ),
            _observation(NOW, 12.0, flow_regime="flowing_baseline"),
        ],
    )

    assert len(signals) == 1
    assert signals[0].evidence["alert_threshold_m3s"] == 10.0
    assert signals[0].evidence["severity_level"] == 3
    assert signals[0].evidence["return_period_years"] == 2


def test_flowing_baseline_below_q2_emits_no_signal():
    signals = evaluate_cell(
        CELL,
        [
            _observation(
                NOW - timedelta(minutes=10), 9.0, flow_regime="flowing_baseline"
            ),
            _observation(NOW, 9.5, flow_regime="flowing_baseline"),
        ],
    )

    assert signals == []


def test_one_reading_above_the_detection_threshold_is_not_enough():
    signals = evaluate_cell(
        CELL,
        [
            _observation(NOW - timedelta(minutes=10), 0.9),
            _observation(NOW, 1.1),
        ],
    )

    assert signals == []


def test_large_sample_gap_breaks_persistence():
    signals = evaluate_cell(
        CELL,
        [
            _observation(NOW - timedelta(hours=1), 1.1),
            _observation(NOW, 1.2),
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


def test_unclassified_station_is_ignored_entirely():
    signals = evaluate_cell(
        CELL,
        [
            _observation(NOW - timedelta(minutes=10), 100.0, flow_regime=None),
            _observation(NOW, 100.0, flow_regime=None),
        ],
    )

    assert signals == []


def test_default_history_lookback_is_one_hour():
    assert FloodPolicy().lookback == timedelta(hours=1)


def test_only_new_target_timestamp_emits_a_signal():
    earlier = NOW - timedelta(minutes=20)
    current = NOW - timedelta(minutes=10)
    signals = evaluate_cell(
        CELL,
        [
            _observation(earlier, 1.1),
            _observation(current, 1.2),
            _observation(NOW, 1.3),
        ],
        target_observed_at={NOW},
    )

    assert [signal.observed_at for signal in signals] == [NOW]
