"""Schema checks for the pending flood station eligibility migration."""

from pathlib import Path


PATH = Path(
    "ecoguard/database/migrations/versions/"
    "0019_flood_station_threshold_status.py"
)
FLOW_REGIME_PATH = Path(
    "ecoguard/database/migrations/versions/"
    "0031_flood_operational_flow_regime.py"
)
MAP_ZOOM_PATH = Path(
    "ecoguard/database/migrations/versions/"
    "0032_remove_hydrometric_map_zoom_level.py"
)


def test_upgrade_removes_obsolete_history_and_baseline_tables():
    source = PATH.read_text(encoding="utf-8")
    upgrade = source.split("def downgrade", 1)[0]
    expected_order = [
        "flood_station_baselines",
        "historical_hydrometric_observations",
        "historical_hydrograph_imports",
        "hydrometric_station_history_links",
        "historical_hydrometric_stations",
    ]

    positions = [
        upgrade.index(f'DROP TABLE IF EXISTS {table}')
        for table in expected_order
    ]

    assert positions == sorted(positions)


def test_flow_regime_migration_is_nullable_and_validated():
    source = FLOW_REGIME_PATH.read_text(encoding="utf-8")

    assert 'down_revision = "planning_failure_police"' in source
    assert "ADD COLUMN operational_flow_regime text" in source
    assert "operational_flow_regime IS NULL" in source
    assert "'ephemeral', 'flowing_baseline'" in source
    assert "source_station_id IN" not in source
    assert "DROP COLUMN IF EXISTS operational_flow_regime" in source


def test_map_zoom_migration_removes_only_the_unused_column():
    source = MAP_ZOOM_PATH.read_text(encoding="utf-8")

    assert 'down_revision = "flood_operational_flow_regime"' in source
    assert "DROP COLUMN IF EXISTS map_zoom_level" in source
    assert "ADD COLUMN map_zoom_level integer" in source
