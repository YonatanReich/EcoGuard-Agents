"""Static audit for the no-op Alembic head merge; never connects to a DB."""

import ast
from pathlib import Path


PATH = Path(
    "ecoguard/database/migrations/versions/"
    "0012_merge_air_pollution_weather_heads.py"
)


def test_air_pollution_and_main_heads_are_joined_without_schema_operations():
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
        "revision": "air_pollution_weather_merge",
        "down_revision": ("0010", "weather_baselines"),
    }

    for name in ("upgrade", "downgrade"):
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        assert not any(isinstance(node, ast.Call) for node in ast.walk(function))
