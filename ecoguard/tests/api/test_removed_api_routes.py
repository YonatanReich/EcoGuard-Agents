"""Regression coverage for retired API serving surfaces."""

from ecoguard.api.main import app


def test_retired_routes_are_not_registered():
    routes = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/api/fire-risk", "POST") not in routes
    assert ("/api/fire-risk/national-scan", "GET") not in routes
    assert ("/api/detected-events", "GET") not in routes
