"""Schema contract for moving flood lifecycle into shared incidents."""

from pathlib import Path


PATH = Path(
    "ecoguard/database/migrations/versions/"
    "0021_flood_incident_lifecycle.py"
)


def test_upgrade_preserves_legacy_rows_before_dropping_parallel_tables():
    source = PATH.read_text(encoding="utf-8")
    upgrade = source.split("def downgrade", 1)[0]

    insert_at = upgrade.index("INSERT INTO incidents")
    drop_candidates_at = upgrade.index("DROP TABLE flood_candidates")
    drop_cursors_at = upgrade.index("DROP TABLE detector_cursors")
    drop_hydrometric_at = upgrade.index("DROP TABLE hydrometric_observations")

    assert insert_at < drop_candidates_at < drop_cursors_at < drop_hydrometric_at


def test_upgrade_does_not_expand_the_shared_incident_schema():
    source = PATH.read_text(encoding="utf-8")
    upgrade = source.split("def downgrade", 1)[0]

    assert "ALTER TABLE incidents" not in upgrade
    assert "lifecycle_key" not in upgrade
    assert "signal_key" not in upgrade
