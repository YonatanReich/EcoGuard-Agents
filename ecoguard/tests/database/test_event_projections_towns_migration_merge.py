"""Static migration-graph audit; this test never connects to a database."""

import ast
from pathlib import Path


PATH = Path(
    "ecoguard/database/migrations/versions/"
    "0016_merge_event_projections_towns_heads.py"
)


def test_event_projections_and_towns_heads_are_joined_without_schema_operations():
    source = PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"revision", "down_revision"}
    }
    assert assignments == {
        "revision": "event_projections_towns_merge",
        "down_revision": ("event_projections", "towns_air_pollution_merge"),
    }

    assert "CREATE TABLE localities" not in source
    for name in ("upgrade", "downgrade"):
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        assert not any(isinstance(node, ast.Call) for node in ast.walk(function))
