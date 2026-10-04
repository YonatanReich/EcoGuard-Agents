from collections import Counter
from datetime import datetime, timedelta, timezone

from ecoguard.api.scenario import SCENARIOS
from ecoguard.demo.scenarios import flood_demo
from ecoguard.detectors.flood.station_rules import evaluate_cell


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _observations(cell_id: str):
    return [
        {
            "source": source,
            "cell_id": cell,
            "observed_at": observed,
            "payload": payload,
        }
        for source, cell, observed, payload in flood_demo.build_rows(NOW)
        if cell == cell_id
    ]


def test_flood_demo_is_registered_with_two_historical_events():
    assert SCENARIOS["flood_demo"] == "ecoguard.demo.scenarios.flood_demo"
    assert [event["id"] for event in flood_demo.GROUND_TRUTH] == ["FD1", "FD2"]
    assert all(event["hazard"] == "flood" for event in flood_demo.GROUND_TRUTH)


def test_flood_demo_builds_only_six_collector_shaped_gauge_rows():
    rows = flood_demo.build_rows(NOW)

    assert len(rows) == 6
    assert Counter(source for source, *_ in rows) == {
        flood_demo.HYDROMETRIC_SOURCE: 6,
    }
    assert {cell for _source, cell, _observed, _payload in rows} == {
        flood_demo.HADERA_CELL,
        flood_demo.ZEELIM_CELL,
    }
    assert all(observed.tzinfo is not None for _, _, observed, _ in rows)


def test_hadera_uses_two_q2_readings_then_emits_a_q5_update():
    observations = _observations(flood_demo.HADERA_CELL)

    assert evaluate_cell(flood_demo.HADERA_CELL, observations[:1]) == []
    confirmation = evaluate_cell(flood_demo.HADERA_CELL, observations[:2])
    all_signals = evaluate_cell(flood_demo.HADERA_CELL, observations)

    assert observations[1]["observed_at"] - observations[0]["observed_at"] == timedelta(
        minutes=12,
        seconds=56,
    )
    assert len(confirmation) == 1
    assert confirmation[0].value == 77.78
    assert confirmation[0].evidence["operational_flow_regime"] == "flowing_baseline"
    assert confirmation[0].evidence["alert_threshold_m3s"] == 32.0
    assert confirmation[0].evidence["return_period_years"] == 2

    assert len(all_signals) == 2
    assert all_signals[-1].value == 92.15
    assert all_signals[-1].evidence["return_period_years"] == 5


def test_zeelim_confirms_at_1635_after_two_readings_above_one():
    observations = _observations(flood_demo.ZEELIM_CELL)

    assert evaluate_cell(flood_demo.ZEELIM_CELL, observations[:2]) == []
    confirmation = evaluate_cell(flood_demo.ZEELIM_CELL, observations)

    assert observations[2]["observed_at"] - observations[1]["observed_at"] == timedelta(
        minutes=17,
        seconds=6,
    )
    assert len(confirmation) == 1
    assert confirmation[0].value == 3.375
    assert confirmation[0].evidence["operational_flow_regime"] == "ephemeral"
    assert confirmation[0].evidence["alert_threshold_m3s"] == 1.0
    assert confirmation[0].evidence["return_period_years"] is None
