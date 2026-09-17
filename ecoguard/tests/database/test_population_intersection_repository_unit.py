"""Offline contract test for the shared population-only repository helper."""

from ecoguard.database.repositories.area_summary import population_intersection


class _MappedResult:
    def mappings(self):
        return self

    def one(self):
        return {
            "grid_available": True,
            "intersected_cell_count": 3,
            "weighted_population": 12.75,
        }


class _Session:
    def __init__(self):
        self.statements = []
        self.parameters = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, parameters):
        self.statements.append(str(statement))
        self.parameters.append(parameters)
        return _MappedResult()


def test_population_intersection_is_one_select_and_preserves_weighted_result():
    session = _Session()
    geometry = {
        "type": "Polygon",
        "coordinates": [[[34.8, 32.0], [34.9, 32.0], [34.9, 32.1], [34.8, 32.0]]],
    }

    result = population_intersection(geometry, session_factory=lambda: session)

    assert result == {
        "grid_available": True,
        "intersected_cell_count": 3,
        "weighted_population": 12.75,
    }
    assert len(session.statements) == 1
    sql = session.statements[0].lower()
    assert "st_intersection" in sql
    assert "st_intersects" in sql
    assert "select" in sql
    assert not {"insert", "update", "delete", "truncate"} & set(sql.split())
    assert session.parameters[0].keys() == {"geojson"}
