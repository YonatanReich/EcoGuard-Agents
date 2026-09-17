from datetime import datetime, timezone

from ecoguard.database.repositories.localities import (
    LocalityLookupStatus,
    nearby_localities,
)


class _Result:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one(self):
        return self.scalar

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, statement, parameters=None):
        self.calls.append((str(statement), parameters))
        return next(self.results)


def test_loaded_layer_returns_normalized_nearby_candidates():
    imported_at = datetime(2026, 9, 17, tzinfo=timezone.utc)
    session = _Session([
        _Result(scalar=True),
        _Result(scalar=True),
        _Result(rows=[{
            "locality_code": "5000",
            "name_he": "תל אביב-יפו",
            "name_en": "Tel Aviv-Yafo",
            "locality_type": "municipality",
            "latitude": 32.0853,
            "longitude": 34.7818,
            "distance_m": 1250.0,
            "source": "official-localities",
            "source_resource_id": "5000",
            "source_updated_at": None,
            "imported_at": imported_at,
            "source_version": "v1",
            "source_checksum": "a" * 64,
            "raw_properties": {"district": "Tel Aviv"},
        }]),
    ])

    result = nearby_localities(
        latitude=32.08,
        longitude=34.78,
        radius_m=10_000.0,
        session_factory=lambda: session,
    )

    assert result.status == LocalityLookupStatus.SUCCESS_WITH_RESULTS
    assert result.candidates[0].locality_code == "5000"
    assert result.candidates[0].distance_m == 1250.0
    query, parameters = session.calls[2]
    assert "ST_DWithin" in query
    assert "representative_point::geography" in query
    assert parameters["radius_m"] == 10_000.0


def test_loaded_layer_with_no_nearby_rows_is_success_empty():
    session = _Session([_Result(scalar=True), _Result(scalar=True), _Result(rows=[])])

    result = nearby_localities(
        latitude=31.0,
        longitude=35.0,
        radius_m=1000.0,
        session_factory=lambda: session,
    )

    assert result.status == LocalityLookupStatus.SUCCESS_EMPTY
    assert result.candidates == []


def test_missing_or_empty_reference_layer_is_not_a_zero_result():
    missing = nearby_localities(
        latitude=31.0,
        longitude=35.0,
        radius_m=1000.0,
        session_factory=lambda: _Session([_Result(scalar=False)]),
    )
    empty = nearby_localities(
        latitude=31.0,
        longitude=35.0,
        radius_m=1000.0,
        session_factory=lambda: _Session([_Result(scalar=True), _Result(scalar=False)]),
    )

    assert missing.status == LocalityLookupStatus.REFERENCE_DATA_NOT_LOADED
    assert empty.status == LocalityLookupStatus.REFERENCE_DATA_NOT_LOADED
    assert missing.reason == empty.reason == "reference_data_not_loaded"
