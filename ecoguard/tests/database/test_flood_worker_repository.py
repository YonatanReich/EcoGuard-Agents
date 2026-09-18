"""PostgreSQL-specific SQL checks for the flood worker repository."""

from ecoguard.database.repositories.flood_worker import (
    PENDING_OBSERVATIONS,
    STATION_STREAM_IDS,
)


def test_pending_query_types_an_empty_cursor_explicitly():
    statement = str(PENDING_OBSERVATIONS)

    assert "CAST(:last_ingested_at AS timestamptz)" in statement
    assert "CAST(:last_observation_id AS bigint)" in statement


def test_stream_id_query_reads_only_confirmed_materialized_matches():
    statement = " ".join(str(STATION_STREAM_IDS).split())

    assert "JOIN flood_station_topology AS topology" in statement
    assert "'stream_id'" in statement
    assert "@> '{\"matched\": true}'::jsonb" in statement
    assert "station.flow_threshold_status = 'complete_thresholds'" in statement
    assert "ST_DWithin" not in statement
