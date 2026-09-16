"""PostgreSQL-specific SQL checks for the flood worker repository."""

from ecoguard.database.repositories.flood_worker import PENDING_OBSERVATIONS


def test_pending_query_types_an_empty_cursor_explicitly():
    statement = str(PENDING_OBSERVATIONS)

    assert "CAST(:last_ingested_at AS timestamptz)" in statement
    assert "CAST(:last_observation_id AS bigint)" in statement
