"""PostgreSQL-specific SQL checks for the flood worker repository."""

from ecoguard.database.repositories.flood_worker import (
    PENDING_OBSERVATIONS,
    STATION_CONTEXTS,
)


def test_pending_query_types_an_empty_cursor_explicitly():
    statement = str(PENDING_OBSERVATIONS)

    assert "CAST(:last_ingested_at AS timestamptz)" in statement
    assert "CAST(:last_observation_id AS bigint)" in statement


def test_station_context_query_reads_materialized_routes_without_spatial_work():
    statement = " ".join(str(STATION_CONTEXTS).split())

    assert "LEFT JOIN flood_station_topology AS topology" in statement
    assert "topology.stream_context" in statement
    assert "topology.downstream_route" in statement
    assert "station.flow_threshold_status = 'complete_thresholds'" in statement
    assert "ST_DWithin" not in statement
