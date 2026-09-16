"""Offline checks for conservative seasonal-baseline construction."""

from ecoguard.collection.flood.static_context import REBUILD_BASELINES


def test_baselines_exclude_the_current_event_and_track_coverage_per_metric():
    sql = " ".join(str(REBUILD_BASELINES).split())

    assert "observed_at < :computed_at - interval '7 days'" in sql
    assert "count(DISTINCT EXTRACT(MONTH" in sql
    assert "count(observation.discharge_m3s)" in sql
    assert "count(observation.water_height_m)" in sql
    assert "discharge_distinct_days" in sql
    assert "stage_distinct_days" in sql
    assert "coverage.covered_months = 12" in sql
    assert "coverage.history_span_days >= 330" in sql
