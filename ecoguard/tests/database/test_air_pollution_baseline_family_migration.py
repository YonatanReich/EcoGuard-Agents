"""Source audit for forward-only family backfill; never connects to a database."""

import ast
from pathlib import Path


PATH = Path("ecoguard/database/migrations/versions/0010_air_pollution_baseline_family.py")


def upgrade_sql():
    source = PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    revision = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in {"revision", "down_revision"}}
    upgrade = next(node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "upgrade")
    calls = [ast.literal_eval(node.value.args[0]).strip()
             for node in upgrade.body if isinstance(node, ast.Expr)
             and isinstance(node.value, ast.Call)]
    return revision, calls


def test_revision_and_exact_operation_order():
    revision, calls = upgrade_sql()
    assert revision == {"revision": "0010", "down_revision": "0009"}
    assert len(calls) == 6
    normalized = [" ".join(item.upper().split()) for item in calls]
    assert "ADD COLUMN BASELINE_FAMILY TEXT" in normalized[0]
    assert "UPDATE AIR_POLLUTION_BASELINE_PROFILES" in normalized[1]
    assert "SET BASELINE_FAMILY = 'COMPLETED_HOUR'" in normalized[1]
    assert "ADD CONSTRAINT AIR_POLLUTION_BASELINE_PROFILES_FAMILY_CK" in normalized[2]
    assert "ALTER COLUMN BASELINE_FAMILY SET NOT NULL" in normalized[3]
    assert "ADD CONSTRAINT AIR_POLLUTION_BASELINE_PROFILES_IDENTITY_FAMILY" in normalized[4]
    assert "DROP CONSTRAINT AIR_POLLUTION_BASELINE_PROFILES_IDENTITY" in normalized[5]


def test_migration_preserves_dependent_tables_and_lifecycle():
    _, calls = upgrade_sql()
    sql = " ".join(calls).upper()
    assert "AIR_POLLUTION_BASELINE_VERSIONS" not in sql
    assert "AIR_POLLUTION_BASELINE_BUCKETS" not in sql
    for forbidden in ("DELETE ", "TRUNCATE ", "DROP TABLE", "DROP INDEX",
                      "LIFECYCLE_STATUS", "CONTENT_SHA256"):
        assert forbidden not in sql


def test_downgrade_refuses_family_erasure():
    source = PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    downgrade = next(node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == "downgrade")
    text = ast.get_source_segment(source, downgrade).upper()
    assert "RAISE RUNTIMEERROR" in text
    assert all(word not in text for word in ("DROP ", "DELETE ", "TRUNCATE "))
