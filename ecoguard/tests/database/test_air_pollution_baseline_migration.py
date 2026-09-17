"""Migration source audit; intentionally does not import Alembic env or connect."""

import ast
from pathlib import Path

PATH = Path("ecoguard/database/migrations/versions/0009_air_pollution_baselines.py")


def test_additive_upgrade_and_revision_chain():
    source = PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
                   if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                   and n.targets[0].id in {"revision", "down_revision"}}
    assert assignments == {"revision": "0009", "down_revision": "0008"}
    upgrade = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    upgrade_source = ast.get_source_segment(source, upgrade).upper()
    assert upgrade_source.count("CREATE TABLE") == 4
    assert upgrade_source.count("CREATE UNIQUE INDEX") == 1
    for destructive in ("DROP TABLE", "DROP INDEX", "DELETE FROM", "TRUNCATE ", "ALTER TABLE"):
        assert destructive not in upgrade_source
    for existing in ("OBSERVATIONS", "COLLECTOR_RUNS", "POPULATION_CELLS"):
        assert f"CREATE TABLE {existing}" not in upgrade_source


def test_downgrade_refuses_destructive_action():
    source = PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    downgrade = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "downgrade")
    text = ast.get_source_segment(source, downgrade).upper()
    assert "RAISE RUNTIMEERROR" in text
    assert all(word not in text for word in ("DROP ", "DELETE ", "TRUNCATE "))
