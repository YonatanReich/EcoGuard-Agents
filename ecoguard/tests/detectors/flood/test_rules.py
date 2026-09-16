"""Focused tests for the new deterministic flood rules."""

from datetime import datetime, timedelta, timezone

from ecoguard.detectors.flood.rules import (
    HYDROMETRIC_SOURCE,
    RADAR_SOURCE,
    RAIN_GAUGE_SOURCE,
    evaluate_cell,
    evaluate_resolutions,
)


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0040-c0012"
CONTEXT = {
    "cell_id": CELL,
    "latitude": 31.8,
    "longitude": 34.8,
    "drainage_basin_id": 3,
    "slope_deg": 1.0,
    "built_up_fraction": 0.1,
    "distance_to_stream_m": 400.0,
}


def _gauge(at, discharge, *, q2=10.0):
    return {
        "source": HYDROMETRIC_SOURCE,
        "cell_id": CELL,
        "observed_at": at,
        "payload": {
            "stations": [
                {
                    "source_station_id": 50,
                    "latitude": 31.81,
                    "longitude": 34.81,
                    "discharge_m3s": discharge,
                    "water_height_m": 1.0,
                    "flow_threshold_2y_m3s": q2,
                    "flow_threshold_5y_m3s": 20.0,
                    "flow_threshold_10y_m3s": 30.0,
                    "flow_threshold_20y_m3s": 40.0,
                    "flow_threshold_50y_m3s": 50.0,
                    "flow_threshold_100y_m3s": 60.0,
                }
            ]
        },
    }


def test_gauge_emits_only_when_an_official_threshold_is_crossed():
    observations = [
        _gauge(NOW - timedelta(minutes=10), 9.0),
        _gauge(NOW, 12.0),
    ]

    candidates = evaluate_cell(CELL, observations, CONTEXT, {})

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.trigger == "gauge_discharge_rating_curve"
    assert candidate.severity_hint == "moderate"
    assert candidate.confidence == 0.88
    assert candidate.location_uncertainty_m == 100.0


def test_gauge_does_not_repeat_while_it_remains_above_threshold():
    observations = [
        _gauge(NOW - timedelta(minutes=10), 11.0),
        _gauge(NOW, 12.0),
    ]

    assert evaluate_cell(CELL, observations, CONTEXT, {}) == []


def test_gauge_finds_a_crossing_when_several_new_samples_arrive_together():
    observations = [
        _gauge(NOW - timedelta(minutes=20), 9.0),
        _gauge(NOW - timedelta(minutes=10), 11.0),
        _gauge(NOW, 12.0),
    ]

    candidate = evaluate_cell(CELL, observations, CONTEXT, {})[0]

    assert candidate.observed_at == NOW - timedelta(minutes=10)


def test_station_month_baseline_is_used_when_rating_curve_is_missing():
    observations = [
        _gauge(NOW - timedelta(minutes=10), 4.0, q2=None),
        _gauge(NOW, 6.0, q2=None),
    ]
    baselines = {
        (50, 9): {
            "discharge_sample_count": 400,
            "discharge_distinct_days": 20,
            "stage_sample_count": 400,
            "stage_distinct_days": 20,
            "covered_months": 12,
            "history_span_days": 365,
            "discharge_p95_m3s": 5.0,
            "stage_p95_m": 2.0,
        }
    }

    candidate = evaluate_cell(CELL, observations, CONTEXT, baselines)[0]

    assert candidate.trigger == "gauge_discharge_seasonal_baseline"
    assert candidate.confidence == 0.76


def test_short_history_is_not_treated_as_a_seasonal_baseline():
    observations = [
        _gauge(NOW - timedelta(minutes=10), 4.0, q2=None),
        _gauge(NOW, 6.0, q2=None),
    ]
    baselines = {
        (50, 9): {
            "discharge_sample_count": 4000,
            "discharge_distinct_days": 25,
            "stage_sample_count": 4000,
            "stage_distinct_days": 25,
            "covered_months": 1,
            "history_span_days": 30,
            "discharge_p95_m3s": 5.0,
            "stage_p95_m": 2.0,
        }
    }

    assert evaluate_cell(CELL, observations, CONTEXT, baselines) == []


def test_short_intense_rain_emits_an_urban_candidate():
    urban = {**CONTEXT, "built_up_fraction": 0.75}
    observations = [
        {
            "source": RAIN_GAUGE_SOURCE,
            "cell_id": CELL,
            "observed_at": NOW,
            "payload": {
                "stations": [
                    {
                        "source_station_id": 205,
                        "rainfall_mm": 8.5,
                        "latitude": 31.8,
                        "longitude": 34.8,
                    }
                ]
            },
        }
    ]

    candidate = evaluate_cell(CELL, observations, urban, {})[0]

    assert candidate.trigger == "urban_rain_10m"
    assert candidate.location_uncertainty_m == 2500.0


def test_accumulated_radar_rain_emits_for_an_ungauged_natural_cell():
    observations = [
        {
            "source": RADAR_SOURCE,
            "cell_id": CELL,
            "observed_at": NOW - timedelta(minutes=15 - 5 * index),
            "payload": {
                "rainfall_mm": 4.0,
                "rain_rate_max_mm_h": 50.0,
            },
        }
        for index in range(4)
    ]

    candidate = evaluate_cell(CELL, observations, CONTEXT, {})[0]

    assert candidate.trigger == "natural_rain_1h"
    assert candidate.severity_hint == "moderate"


def test_rain_finds_a_crossing_before_the_latest_still_high_frame():
    observations = [
        {
            "source": RADAR_SOURCE,
            "cell_id": CELL,
            "observed_at": NOW - timedelta(minutes=20 - 5 * index),
            "payload": {
                "rainfall_mm": 4.0,
                "rain_rate_max_mm_h": 50.0,
            },
        }
        for index in range(5)
    ]

    candidate = evaluate_cell(CELL, observations, CONTEXT, {})[0]

    assert candidate.observed_at == NOW - timedelta(minutes=5)


def test_rain_only_detection_requires_materialized_geographic_context():
    observations = [
        {
            "source": RADAR_SOURCE,
            "cell_id": CELL,
            "observed_at": NOW,
            "payload": {"rainfall_mm": 20.0, "rain_rate_max_mm_h": 80.0},
        }
    ]

    assert evaluate_cell(CELL, observations, None, {}) == []


def test_gauge_event_resolves_after_two_readings_below_the_exit_threshold():
    opened_at = NOW - timedelta(minutes=30)
    active = {
        "event_key": f"flood:gauge:{CELL}:50",
        "candidate_key": "candidate-1",
        "cell_id": CELL,
        "opened_at": opened_at,
        "trigger": "gauge_discharge_rating_curve",
        "evidence": {"source_station_id": 50, "threshold": 10.0},
    }
    observations = [
        _gauge(NOW - timedelta(minutes=10), 7.5),
        _gauge(NOW, 7.0),
    ]

    resolutions = evaluate_resolutions(observations, CONTEXT, [active])

    assert len(resolutions) == 1
    assert resolutions[0].event_key == active["event_key"]
    assert resolutions[0].reason == "gauge_below_exit_threshold"


def test_gauge_event_stays_active_near_the_opening_threshold():
    active = {
        "event_key": f"flood:gauge:{CELL}:50",
        "candidate_key": "candidate-1",
        "cell_id": CELL,
        "opened_at": NOW - timedelta(minutes=30),
        "trigger": "gauge_discharge_rating_curve",
        "evidence": {"source_station_id": 50, "threshold": 10.0},
    }
    observations = [
        _gauge(NOW - timedelta(minutes=10), 7.5),
        _gauge(NOW, 8.5),
    ]

    assert evaluate_resolutions(observations, CONTEXT, [active]) == []


def test_missing_observations_never_resolve_an_active_event():
    active = {
        "event_key": f"flood:gauge:{CELL}:50",
        "candidate_key": "candidate-1",
        "cell_id": CELL,
        "opened_at": NOW - timedelta(minutes=30),
        "trigger": "gauge_discharge_rating_curve",
        "evidence": {"source_station_id": 50, "threshold": 10.0},
    }

    assert evaluate_resolutions([], CONTEXT, [active]) == []


def test_rain_event_resolves_from_two_dry_radar_heartbeats():
    opened_at = NOW - timedelta(minutes=20)
    active = {
        "event_key": f"flood:rain:{CELL}",
        "candidate_key": "candidate-2",
        "cell_id": CELL,
        "opened_at": opened_at,
        "trigger": "urban_rain_10m",
        "evidence": {"threshold": 8.0},
    }
    urban = {**CONTEXT, "built_up_fraction": 0.75}
    observations = [
        {
            "source": RADAR_SOURCE,
            "cell_id": CELL,
            "observed_at": opened_at,
            "payload": {"rainfall_mm": 9.0, "rain_rate_max_mm_h": 80.0},
        },
        {
            "source": RADAR_SOURCE,
            "cell_id": CELL,
            "observed_at": NOW - timedelta(minutes=5),
            "payload": {"rainfall_mm": 0.0, "rain_rate_max_mm_h": 0.0},
        },
        {
            "source": RADAR_SOURCE,
            "cell_id": CELL,
            "observed_at": NOW,
            "payload": {"rainfall_mm": 0.0, "rain_rate_max_mm_h": 0.0},
        },
    ]

    resolutions = evaluate_resolutions(observations, urban, [active])

    assert len(resolutions) == 1
    assert resolutions[0].reason == "rain_below_exit_threshold"
