"""Generic event projection migration and repository contract tests."""

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "0015_event_projections.py"
)


def test_projection_migration_is_generic_and_follows_single_head():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "event_projections"' in source
    assert 'down_revision = "air_pollution_firms_merge"' in source
    assert "CREATE TABLE event_projections" in source
    assert "incident_id                  text        PRIMARY KEY" in source
    assert "REFERENCES incidents(id)" in source
    assert "analysis_id" in source
    assert "coordinator_routing_id" in source
    assert "air_pollution_event" not in source
