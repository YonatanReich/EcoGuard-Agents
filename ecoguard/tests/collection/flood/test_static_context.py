"""Offline checks for materialized flood context."""

from ecoguard.collection.flood.static_context import (
    ENRICH_CELLS,
    STATION_TOPOLOGY_INPUT,
    STREAM_NETWORK_INPUT,
)


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
    assert "station.flow_threshold_status = 'complete_thresholds'" in station_sql
    assert "stream.draining_water_id" in station_sql
    assert "FROM stream_network_nodes AS node" in network_sql
    assert "LEFT JOIN stream_network_edges AS edge" in network_sql
