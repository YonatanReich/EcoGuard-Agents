from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "0016_localities.py"
)


def test_localities_migration_follows_event_projection_head_and_is_unseeded():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "localities"' in source
    assert 'down_revision = "event_projections"' in source
    assert "CREATE TABLE localities" in source
    assert "geometry(MultiPolygon, 4326)" in source
    assert "geometry(Point, 4326)" in source
    assert "localities_boundary_gix" in source
    assert "localities_representative_point_gix" in source
    assert "localities_representative_point_geography_gix" in source
    assert "INSERT INTO localities" not in source
