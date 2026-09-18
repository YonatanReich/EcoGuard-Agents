from ecoguard.database.repositories.towns import TownLookupStatus, nearby_towns


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


def test_loaded_towns_return_polygon_selected_candidates_for_air_pollution():
    session = _Session([
        _Result(scalar=True),
        _Result(scalar=True),
        _Result(rows=[{
            "town_id": "cbs-5000",
            "name_he": "Tel Aviv-Yafo",
            "name_en": "Tel Aviv-Yafo",
            "place": "city",
            "cbs_code": "5000",
            "population": 490_000,
            "latitude": 32.0853,
            "longitude": 34.7818,
            "distance_m": 0.0,
            "outline_source": "municipal boundary",
            "authority": "Tel Aviv-Yafo Municipality",
            "authority_type": "municipality",
            "fire_district": "Dan",
            "police_station": "Lev Tel Aviv",
        }]),
    ])

    result = nearby_towns(
        latitude=32.08,
        longitude=34.78,
        radius_m=10_000.0,
        session_factory=lambda: session,
    )

    assert result.status == TownLookupStatus.SUCCESS_WITH_RESULTS
    assert result.source == "shared_postgis_towns"
    assert result.candidates[0].town_id == "cbs-5000"
    assert result.candidates[0].population == 490_000
    query, parameters = session.calls[2]
    assert "ST_DWithin(outline" in query
    assert "ST_Distance(outline" in query
    assert "label_lat AS latitude" in query
    assert parameters["radius_m"] == 10_000.0


def test_loaded_towns_with_no_nearby_rows_is_success_empty():
    session = _Session([_Result(scalar=True), _Result(scalar=True), _Result(rows=[])])

    result = nearby_towns(
        latitude=31.0,
        longitude=35.0,
        radius_m=1000.0,
        session_factory=lambda: session,
    )

    assert result.status == TownLookupStatus.SUCCESS_EMPTY
    assert result.candidates == []


def test_missing_or_empty_towns_reference_layer_is_not_a_zero_result():
    missing = nearby_towns(
        latitude=31.0,
        longitude=35.0,
        radius_m=1000.0,
        session_factory=lambda: _Session([_Result(scalar=False)]),
    )
    empty = nearby_towns(
        latitude=31.0,
        longitude=35.0,
        radius_m=1000.0,
        session_factory=lambda: _Session([_Result(scalar=True), _Result(scalar=False)]),
    )

    assert missing.status == TownLookupStatus.REFERENCE_DATA_NOT_LOADED
    assert empty.status == TownLookupStatus.REFERENCE_DATA_NOT_LOADED
    assert missing.reason == empty.reason == "reference_data_not_loaded"
