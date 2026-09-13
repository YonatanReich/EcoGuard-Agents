"""Offline tests for the standalone Nominatim geocoding service."""

from pathlib import Path

import pytest
import requests

from ecoguard.shared.geocoding import NominatimGeocoder


class FakeClock:
    def __init__(self, value: float = 1_700_000_000.0):
        self.value = value
        self.sleeps = []

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None, malformed=False):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.malformed = malformed

    def json(self):
        if self.malformed:
            raise ValueError("malformed")
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def candidate(
    *,
    city="פתח תקווה",
    road=None,
    neighborhood=None,
    country="il",
    lat="32.084",
    lon="34.887",
    importance=0.5,
):
    address = {"country_code": country, "city": city}
    if road is not None:
        address["road"] = road
    if neighborhood is not None:
        address["neighbourhood"] = neighborhood
    return {
        "lat": lat,
        "lon": lon,
        "display_name": "validated result",
        "importance": importance,
        "address": address,
        "namedetails": {},
    }


@pytest.fixture()
def make_geocoder(tmp_path: Path):
    def factory(responses, **kwargs):
        clock = kwargs.pop("clock", FakeClock())
        session = FakeSession(responses)
        geocoder = NominatimGeocoder(
            base_url="https://nominatim.example",
            user_agent="EcoGuard-Tests/1.0 test@example.com",
            cache_path=tmp_path / "cache.sqlite3",
            session=session,
            clock=clock,
            sleep=clock.sleep,
            **kwargs,
        )
        return geocoder, session, clock

    return factory


def test_low_confidence_is_skipped_without_request(make_geocoder):
    geocoder, session, _ = make_geocoder([])

    result = geocoder.geocode({"city": "חיפה", "confidence": 0.79})

    assert result["status"] == "skipped"
    assert session.calls == []


def test_missing_city_is_skipped_without_request(make_geocoder):
    geocoder, session, _ = make_geocoder([])

    result = geocoder.geocode({"street": "הרצל", "confidence": 0.95})

    assert result["status"] == "skipped"
    assert result["latitude"] is None
    assert session.calls == []


def test_missing_configuration_is_skipped(tmp_path: Path):
    geocoder = NominatimGeocoder(
        base_url="",
        user_agent="",
        cache_path=tmp_path / "cache.sqlite3",
        session=FakeSession([]),
    )

    assert geocoder.geocode({"city": "חיפה", "confidence": 0.9})["status"] == "skipped"


def test_street_and_city_query_resolves_with_street_precision(make_geocoder):
    geocoder, session, _ = make_geocoder([FakeResponse([candidate(road="הרצל")])])

    result = geocoder.geocode(
        {"city": "פתח תקווה", "street": "הרצל", "confidence": 0.95}
    )

    assert result["status"] == "resolved"
    assert result["precision"] == "street"
    assert result["confidence"] == 0.95
    params = session.calls[0][1]["params"]
    assert params["street"] == "הרצל"
    assert params["city"] == "פתח תקווה"
    assert params["countrycodes"] == "il"


def test_neighborhood_query_resolves_with_neighborhood_precision(make_geocoder):
    geocoder, session, _ = make_geocoder(
        [FakeResponse([candidate(city="חיפה", neighborhood="זיו")])]
    )

    result = geocoder.geocode(
        {"city": "חיפה", "neighborhood": "זיו", "confidence": 0.9}
    )

    assert result["precision"] == "neighborhood"
    assert result["confidence"] == 0.85
    assert "q" in session.calls[0][1]["params"]


def test_wrong_neighborhood_falls_back_to_city(make_geocoder):
    geocoder, _, _ = make_geocoder(
        [
            FakeResponse([candidate(city="חיפה", neighborhood="כרמל")]),
            FakeResponse([candidate(city="חיפה")]),
        ]
    )

    result = geocoder.geocode(
        {"city": "חיפה", "neighborhood": "זיו", "confidence": 0.9}
    )

    assert result["precision"] == "city"


def test_city_only_query_is_coarse_city_precision(make_geocoder):
    geocoder, _, _ = make_geocoder([FakeResponse([candidate()])])

    result = geocoder.geocode({"city": "פתח תקווה", "confidence": 0.85})

    assert result["precision"] == "city"
    assert result["confidence"] == 0.70


@pytest.mark.parametrize(
    "result_candidate",
    [candidate(country="us"), candidate(city="חיפה")],
)
def test_wrong_country_or_city_is_rejected_and_city_fallback_can_resolve(
    make_geocoder,
    result_candidate,
):
    geocoder, _, _ = make_geocoder(
        [FakeResponse([result_candidate]), FakeResponse([candidate()])]
    )

    result = geocoder.geocode(
        {"city": "פתח תקווה", "street": "הרצל", "confidence": 0.95}
    )

    assert result["precision"] == "city"


def test_wrong_street_is_rejected(make_geocoder):
    geocoder, _, _ = make_geocoder(
        [FakeResponse([candidate(road="אחר")]), FakeResponse([candidate()])]
    )

    result = geocoder.geocode(
        {"city": "פתח תקווה", "street": "הרצל", "confidence": 0.95}
    )

    assert result["precision"] == "city"


def test_later_valid_result_is_selected(make_geocoder):
    geocoder, _, _ = make_geocoder(
        [
            FakeResponse(
                [candidate(city="חיפה", road="הרצל", importance=0.9), candidate(road="הרצל")]
            )
        ]
    )

    result = geocoder.geocode(
        {"city": "פתח תקווה", "street": "הרצל", "confidence": 0.95}
    )

    assert result["precision"] == "street"


def test_resolved_cache_hit_avoids_second_request(make_geocoder):
    geocoder, session, _ = make_geocoder([FakeResponse([candidate()])])
    location = {"city": "פתח תקווה", "confidence": 0.85}

    first = geocoder.geocode(location)
    second = geocoder.geocode(location)

    assert first == second
    assert len(session.calls) == 1


def test_not_found_cache_hit_avoids_second_request(make_geocoder):
    geocoder, session, _ = make_geocoder([FakeResponse([])])
    location = {"city": "פתח תקווה", "confidence": 0.85}

    first = geocoder.geocode(location)
    second = geocoder.geocode(location)

    assert first["status"] == "not_found"
    assert second == first
    assert len(session.calls) == 1


def test_cache_expiry_causes_new_request(make_geocoder):
    clock = FakeClock()
    geocoder, session, _ = make_geocoder(
        [FakeResponse([candidate()]), FakeResponse([candidate()])], clock=clock
    )
    location = {"city": "פתח תקווה", "confidence": 0.85}
    geocoder.geocode(location)
    clock.value += 31 * 24 * 60 * 60

    geocoder.geocode(location)

    assert len(session.calls) == 2


def test_uncached_requests_are_rate_limited(make_geocoder):
    geocoder, _, clock = make_geocoder(
        [FakeResponse([]), FakeResponse([candidate(city="חיפה")])]
    )
    geocoder.geocode({"city": "פתח תקווה", "confidence": 0.85})
    geocoder.geocode({"city": "חיפה", "confidence": 0.85})

    assert clock.sleeps == [15.0]


@pytest.mark.parametrize("status_code", [403, 429])
def test_forbidden_and_rate_limited_are_errors_not_cached(make_geocoder, status_code):
    geocoder, session, _ = make_geocoder(
        [FakeResponse([], status_code=status_code), FakeResponse([candidate()])]
    )
    location = {"city": "פתח תקווה", "confidence": 0.85}

    assert geocoder.geocode(location)["status"] == "error"
    assert geocoder.geocode(location)["status"] == "resolved"
    assert len(session.calls) == 2


def test_retry_after_delays_the_next_uncached_request(make_geocoder):
    geocoder, _, clock = make_geocoder(
        [
            FakeResponse([], status_code=429, headers={"Retry-After": "60"}),
            FakeResponse([candidate(city="חיפה")]),
        ]
    )
    geocoder.geocode({"city": "פתח תקווה", "confidence": 0.85})

    geocoder.geocode({"city": "חיפה", "confidence": 0.85})

    assert clock.sleeps == [60.0]


def test_timeout_is_error_without_coordinates(make_geocoder):
    geocoder, _, _ = make_geocoder([requests.Timeout("timeout")])

    result = geocoder.geocode({"city": "פתח תקווה", "confidence": 0.85})

    assert result["status"] == "error"
    assert result["latitude"] is None
    assert result["longitude"] is None


def test_malformed_response_is_error(make_geocoder):
    geocoder, _, _ = make_geocoder([FakeResponse(malformed=True)])

    result = geocoder.geocode({"city": "פתח תקווה", "confidence": 0.85})

    assert result["status"] == "error"


def test_invalid_coordinates_produce_not_found_without_fabrication(make_geocoder):
    geocoder, _, _ = make_geocoder([FakeResponse([candidate(lat="not-a-number")])])

    result = geocoder.geocode({"city": "פתח תקווה", "confidence": 0.85})

    assert result["status"] == "not_found"
    assert result["latitude"] is None
    assert result["longitude"] is None


def test_empty_valid_response_is_not_found(make_geocoder):
    geocoder, _, _ = make_geocoder([FakeResponse([])])

    result = geocoder.geocode({"city": "פתח תקווה", "confidence": 0.85})

    assert result["status"] == "not_found"
    assert result["precision"] is None
