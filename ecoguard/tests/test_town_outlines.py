"""The settlement-outline lookup behind the map's affected/at-risk glow."""

from fastapi.testclient import TestClient

from ecoguard.api.main import app
from ecoguard.database.repositories.towns import town_outlines


def test_nothing_asked_for_returns_an_empty_collection_without_a_query():
    assert town_outlines(ids=[], names=[]) == {"type": "FeatureCollection", "features": []}


def test_rejects_oversized_requests():
    params = [("id", str(index)) for index in range(201)]
    assert TestClient(app).get("/api/towns/outlines", params=params).status_code == 422
