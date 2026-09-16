"""Offline checks for conservative seasonal-baseline construction."""

from ecoguard.collection.flood.static_context import (
    ENRICH_CELLS,
    REBUILD_BASELINES,
    STATION_TOPOLOGY_INPUT,
    STREAM_NETWORK_INPUT,
)


def test_baselines_exclude_the_current_event_and_track_coverage_per_metric():
    sql = " ".join(str(REBUILD_BASELINES).split())

    assert "observed_at < :computed_at - interval '7 days'" in sql
    assert "historical_hydrometric_observations" in sql
    assert "hydrometric_station_history_links" in sql
    assert "WHERE NOT observation.is_sewage" in sql
    assert "NULL::double precision AS water_height_m" in sql
    assert "GROUP BY observation.hydrometric_station_id, observation.observed_at" in sql
    assert "count(DISTINCT EXTRACT(MONTH" in sql
    assert "count(observation.discharge_m3s)" in sql
    assert "count(observation.water_height_m)" in sql
    assert "discharge_distinct_days" in sql
    assert "stage_distinct_days" in sql
    assert "coverage.covered_months = 12" in sql
    assert "coverage.history_span_days >= 330" in sql
    assert "count(observation.discharge_m3s) >= 300" in sql
    assert "count(observation.water_height_m) >= 300" in sql


def test_static_context_samples_urban_cover_and_preserves_unknown_status():
    sql = " ".join(str(ENRICH_CELLS).split())

    assert "sample_offset(east_m, north_m)" in sql
    assert "count(sampled.built_up)" in sql
    assert "urban.sample_count >= :minimum_urban_samples" in sql
    assert "THEN 'classified' ELSE 'unknown'" in sql


def test_station_routes_are_built_from_cached_stream_topology():
    station_sql = " ".join(str(STATION_TOPOLOGY_INPUT).split())
    network_sql = " ".join(str(STREAM_NETWORK_INPUT).split())

    assert "station.drainage_basin_id" in station_sql
    assert "ST_DWithin" in station_sql
    assert "stream.draining_water_id" in station_sql
    assert "FROM stream_network_nodes AS node" in network_sql
    assert "LEFT JOIN stream_network_edges AS edge" in network_sql
