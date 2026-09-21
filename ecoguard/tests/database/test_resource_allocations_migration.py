"""Schema contract for durable emergency-station allocations."""

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "0016_resource_allocations.py"
)
EARTHQUAKE_POLICY_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "0022_earthquake_allocation_policy.py"
)


def test_resource_allocations_follow_the_current_migration_head():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "resource_allocations"' in source
    assert 'down_revision = "event_projections"' in source


def test_resource_allocations_reference_exactly_one_station():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "REFERENCES incidents(id)" in source
    assert "REFERENCES fire_stations(id)" in source
    assert "REFERENCES police_stations(id)" in source
    assert "REFERENCES mda_stations(id)" in source
    assert "num_nonnulls(" in source
    assert ") = 1" in source


def test_active_station_claims_are_unique_and_release_is_historical():
    source = MIGRATION.read_text(encoding="utf-8")

    assert source.count("CREATE UNIQUE INDEX resource_allocations_active_") == 3
    assert "WHERE released_at IS NULL" in source
    assert "released_at        timestamptz" in source
    assert "release_reason     text" in source


def test_earthquake_policy_allocations_store_policy_without_fake_risk():
    source = EARTHQUAKE_POLICY_MIGRATION.read_text(encoding="utf-8")

    assert 'down_revision = "flood_incident_lifecycle"' in source
    assert "ALTER COLUMN risk_score DROP NOT NULL" in source
    assert "ALTER COLUMN risk_level DROP NOT NULL" in source
    assert "earthquake_minimum_response_v1" in source
    assert "protocol_recommended_units" in source
    assert "ecoguard_minimum_response_policy" in source
