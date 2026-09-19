"""Schema checks for the pending flood station eligibility migration."""

from pathlib import Path


PATH = Path(
    "ecoguard/database/migrations/versions/"
    "0019_flood_station_threshold_status.py"
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
