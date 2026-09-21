from ecoguard.database.repositories.towns import (
    TownLookupStatus,
    nearby_towns,
    resolve_named_town,
    responsible_police_stations,
    town_at_location,
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

    def first(self):
        return self.rows[0] if self.rows else None


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


def test_named_town_uses_outline_not_label_point_for_signal_relation():
    session = _Session([
        _Result(scalar=True),
        _Result(scalar=True),
        _Result(rows=[{
            "town_id": "mevaseret-zion",
            "name_he": "מבשרת ציון",
            "name_en": "Mevaseret Zion",
            "place": "town",
            "cbs_code": "1015",
            "outline_source": "fabric/admin8",
            "authority": "מבשרת ציון",
            "authority_type": "מועצה מקומית",
            "distance_m": 0.0,
            "contains_signal": True,
        }]),
    ])

    result = resolve_named_town(
        candidate_names=["מבשרת ציון", "מבשרת"],
        latitude=31.80,
        longitude=35.15,
        session_factory=lambda: session,
    )

    assert result.status == TownLookupStatus.SUCCESS_WITH_RESULTS
    assert result.match is not None
    assert result.match.name_he == "מבשרת ציון"
    assert result.match.contains_signal is True
    query, parameters = session.calls[2]
    assert "name_he = ANY" in query
    assert "ST_Covers(outline::geometry" in query
    assert "ST_Distance(outline" in query
    assert "label_lat" not in query
    assert parameters["candidate_names"] == ["מבשרת ציון", "מבשרת"]
def test_responsible_police_stations_returns_internal_database_keys():
    session = _Session([
        _Result(rows=[{
            "town_id": "haifa",
            "name_he": "חיפה",
            "police_station_ids": [12, 18, 21],
        }]),
    ])

    result = responsible_police_stations(
        latitude=32.794,
        longitude=34.990,
        session_factory=lambda: session,
    )

    assert result == {
        "town_id": "haifa",
        "town_name": "חיפה",
        "police_station_ids": [12, 18, 21],
    }
    query, parameters = session.calls[0]
    assert "ST_Covers" in query
    assert "town_police_stations" in query
    assert parameters == {"latitude": 32.794, "longitude": 34.990}


def test_responsible_police_stations_returns_none_outside_every_town():
    result = responsible_police_stations(
        latitude=31.0,
        longitude=35.0,
        session_factory=lambda: _Session([_Result(rows=[])]),
    )

    assert result is None


def test_town_at_location_returns_full_contact_record():
    row = {
        "town_id": "haifa",
        "name_he": "חיפה",
        "name_en": "Haifa",
        "place": "city",
        "population": 295_000,
        "households": 120_000,
        "cbs_code": "4000",
        "outline_source": "municipal boundary",
        "fire_district": "חוף",
        "authority": "חיפה",
        "authority_type": "עירייה",
        "authority_phone": "04-8356860",
        "authority_address": "חסן שוקרי 14",
        "authority_website": "https://www.haifa.muni.il",
        "police_station": "תחנת חיפה",
        "police_region": "מרחב כרמל",
        "police_district": "חוף",
        "area_km2": 64.6,
        "label_lat": 32.794,
        "label_lon": 34.9896,
        "min_lon": 34.9,
        "min_lat": 32.7,
        "max_lon": 35.1,
        "max_lat": 32.9,
    }
    session = _Session([_Result(rows=[row])])

    result = town_at_location(
        latitude=32.794,
        longitude=34.9896,
        session_factory=lambda: session,
    )

    assert result is not None
    assert result["town_id"] == "haifa"
    assert result["authority_phone"] == "04-8356860"
    assert result["authority_website"] == "https://www.haifa.muni.il"
    query, parameters = session.calls[0]
    assert "ST_Covers" in query
    assert parameters == {"latitude": 32.794, "longitude": 34.9896}
