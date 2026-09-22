"""The event panel's "who to call" lookup: shaping and fallbacks, no database."""

from fastapi.testclient import TestClient

from ecoguard.api.main import app
from ecoguard.database.repositories import responsible_services


class _OneRowSession:
    """Stands in for a Session whose single statement returns `row`."""

    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        return self

    def mappings(self):
        return self

    def one(self):
        return self.row


def _station(name, distance_m=1234.4):
    return {"name": name, "address": "addr", "phone": "04-1234567", "distance_m": distance_m}


def test_police_is_the_towns_linked_station_when_there_is_one(monkeypatch):
    row = {
        "town": {"name_he": "נשר", "name_en": "Nesher", "authority": "נשר", "authority_type": "עירייה",
                 "authority_phone": "04-8299777", "authority_address": None, "authority_website": None,
                 "fire_district": "חוף", "distance_m": 0},
        "linked_police": _station("תחנת נשר"),
        "nearest_police": _station("תחנת זבולון"),
        "nearest_fire": _station("נשר"),
        "nearest_mda": None,
    }
    monkeypatch.setattr(responsible_services, "Session", lambda: _OneRowSession(row))

    result = responsible_services.responsible_parties_at(latitude=32.77, longitude=35.04)

    assert result["police_station"]["name"] == "תחנת נשר"
    assert result["police_station"]["basis"] == "responsible"
    assert result["authority"]["phone"] == "04-8299777"
    assert result["nearest_fire_station"]["distance_m"] == 1234
    assert result["nearest_mda_station"] is None


def test_police_falls_back_to_nearest_and_says_so(monkeypatch):
    row = {"town": None, "linked_police": None, "nearest_police": _station("תחנת זבולון"),
           "nearest_fire": None, "nearest_mda": None}
    monkeypatch.setattr(responsible_services, "Session", lambda: _OneRowSession(row))

    result = responsible_services.responsible_parties_at(latitude=32.8, longitude=35.07)

    assert result["authority"] is None
    assert result["police_station"]["basis"] == "nearest"


def test_rejects_points_outside_the_service_area():
    response = TestClient(app).get("/api/responsible-parties", params={"latitude": 40, "longitude": 35})
    assert response.status_code == 422
