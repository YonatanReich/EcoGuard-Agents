"""Turning a written place name into a coordinate.

Used by the text lane, where a report says "the industrial zone in Haifa"
rather than giving a position.

Answers are checked before they are accepted - a provider will happily match a
street in one town with a street of the same name in another - and cached on
disk, because the same places recur constantly and the provider is a free
service with a rate limit."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from typing import Callable

import requests


MIN_LOCATION_CONFIDENCE = 0.80
MIN_REQUEST_INTERVAL_SECONDS = 15.0
RESOLVED_TTL_SECONDS = 30 * 24 * 60 * 60
NOT_FOUND_TTL_SECONDS = 24 * 60 * 60
DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "generated"
    / "nominatim_geocode_cache.sqlite3"
)

_ADDRESS_CITY_FIELDS = ("city", "town", "village", "municipality", "locality")
_ADDRESS_NEIGHBORHOOD_FIELDS = (
    "neighbourhood",
    "suburb",
    "quarter",
    "city_district",
)
_NIQQUD_PATTERN = re.compile(
    "[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]"
)


def _empty_result(status: str, query: str | None = None) -> dict:
    """A result carrying no coordinate, and the reason there is none."""
    return {
        "latitude": None,
        "longitude": None,
        "display_name": None,
        "query": query,
        "confidence": 0.0,
        "precision": None,
        "status": status,
    }


def _normalize(value: object) -> str:
    """A name in one spelling, so two writings of the same place compare equal."""
    text = _NIQQUD_PATTERN.sub("", str(value or ""))
    text = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in text
    )
    return " ".join(text.casefold().split())


class NominatimGeocoder:
    """Resolve structured locations without fabricating provider results."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        user_agent: str | None = None,
        cache_path: Path | str = DEFAULT_CACHE_PATH,
        session: object | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        country_codes: str = "il",
    ) -> None:
        """Build the geocoder. Transport, cache and clock are injectable for testing."""
        configured_base_url = (
            os.getenv("NOMINATIM_BASE_URL") if base_url is None else base_url
        )
        configured_user_agent = (
            os.getenv("NOMINATIM_USER_AGENT")
            if user_agent is None
            else user_agent
        )
        self.base_url = (configured_base_url or "").rstrip("/")
        self.user_agent = configured_user_agent or ""
        # Both the request filter and the accepted-result check come from this
        # one value, so they cannot drift apart. The default keeps every
        # existing caller on Israel alone; a caller that needs the West Bank,
        # which OpenStreetMap files under "ps", passes "il,ps".
        self.country_codes = country_codes
        self._accepted_countries = frozenset(
            code.strip() for code in country_codes.split(",") if code.strip()
        )
        self.cache_path = Path(cache_path)
        self.session = session or requests.Session()
        self.clock = clock
        self.sleep = sleep
        self._request_lock = threading.Lock()
        self._last_request_at: float | None = None
        self._blocked_until = 0.0
        self._initialize_cache()

    def _initialize_cache(self) -> None:
        """Prepare the on-disk cache, so a place looked up once is not looked up again."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.cache_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    cache_key TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )

    def _cache_key(self, kind: str, components: dict) -> str:
        """A stable key for one lookup."""
        payload = json.dumps(
            {
                "base_url": self.base_url,
                "country_codes": self.country_codes,
                "kind": kind,
                "components": {
                    key: _normalize(value) for key, value in components.items()
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cached(self, cache_key: str) -> dict | None:
        """A previous answer for this lookup, when one is still fresh."""
        now = self.clock()
        with sqlite3.connect(self.cache_path) as connection:
            row = connection.execute(
                "SELECT result_json, expires_at FROM geocode_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            if row[1] <= now:
                connection.execute(
                    "DELETE FROM geocode_cache WHERE cache_key = ?", (cache_key,)
                )
                return None
        return json.loads(row[0])

    def _store(self, cache_key: str, result: dict, ttl_seconds: int) -> None:
        """Keep an answer for later, for as long as it stays useful."""
        with sqlite3.connect(self.cache_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO geocode_cache VALUES (?, ?, ?)",
                (
                    cache_key,
                    json.dumps(result, ensure_ascii=False),
                    self.clock() + ttl_seconds,
                ),
            )

    def _wait_for_rate_limit(self) -> None:
        """Wait if necessary, so the provider's rate limit is respected."""
        now = self.clock()
        wait_until = self._blocked_until
        if self._last_request_at is not None:
            wait_until = max(
                wait_until,
                self._last_request_at + MIN_REQUEST_INTERVAL_SECONDS,
            )
        delay = wait_until - now
        if delay > 0:
            self.sleep(delay)

    def _record_retry_after(self, response: object) -> None:
        """Note how long the provider asked us to wait."""
        value = getattr(response, "headers", {}).get("Retry-After")
        if value is None:
            return
        try:
            seconds = max(0.0, min(float(value), 300.0))
        except (TypeError, ValueError):
            return
        self._blocked_until = max(self._blocked_until, self.clock() + seconds)

    def _query(self, kind: str, components: dict) -> tuple[dict, str]:
        """The request parameters for one kind of lookup."""
        common = {
            "format": "jsonv2",
            "addressdetails": 1,
            "namedetails": 1,
            "countrycodes": self.country_codes,
            "layer": "address",
            "limit": 5,
            "accept-language": "he",
        }
        city = components["city"]
        if kind == "street":
            common.update({"street": components["street"], "city": city})
            return common, f"{components['street']}, {city}, Israel"
        if kind == "neighborhood":
            query = f"{components['neighborhood']}, {city}, ישראל"
            common["q"] = query
            return common, query
        common["city"] = city
        return common, f"{city}, Israel"

    @staticmethod
    def _matches_expected(value: object, expected: str) -> bool:
        """Whether two names refer to the same place, ignoring spelling differences."""
        return _normalize(value) == _normalize(expected)

    def _valid_candidate(
        self,
        candidate: dict,
        kind: str,
        components: dict,
    ) -> tuple[float, float, float] | None:
        """One candidate answer, or None when it is not the place that was asked for.

        A provider will happily answer a street in one town with a street of the
        same name in another, so the town, the street and the country all have to
        match before a coordinate is accepted.
        """
        address = candidate.get("address")
        if (
            not isinstance(address, dict)
            or address.get("country_code") not in self._accepted_countries
        ):
            return None

        expected_city = components["city"]
        if not any(
            self._matches_expected(address.get(field), expected_city)
            for field in _ADDRESS_CITY_FIELDS
        ):
            return None

        if kind == "street":
            expected = components["street"]
            namedetails = candidate.get("namedetails") or {}
            names = namedetails.values() if isinstance(namedetails, dict) else ()
            if not self._matches_expected(address.get("road"), expected) and not any(
                self._matches_expected(name, expected) for name in names
            ):
                return None
        elif kind == "neighborhood":
            expected = components["neighborhood"]
            if not any(
                self._matches_expected(address.get(field), expected)
                for field in _ADDRESS_NEIGHBORHOOD_FIELDS
            ):
                return None

        try:
            latitude = float(candidate["lat"])
            longitude = float(candidate["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            return None
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return None
        try:
            importance = float(candidate.get("importance", 0.0))
        except (TypeError, ValueError):
            importance = 0.0
        return latitude, longitude, importance

    def _request(self, kind: str, components: dict) -> dict:
        """Make one lookup, answering from the cache when it can."""
        params, query_text = self._query(kind, components)
        cache_key = self._cache_key(kind, components)
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        with self._request_lock:
            cached = self._cached(cache_key)
            if cached is not None:
                return cached
            self._wait_for_rate_limit()
            try:
                response = self.session.get(
                    f"{self.base_url}/search",
                    params=params,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "application/json",
                    },
                    timeout=20,
                )
            except requests.RequestException:
                return _empty_result("error", query_text)
            finally:
                self._last_request_at = self.clock()

            if response.status_code in (403, 429):
                self._record_retry_after(response)
                return _empty_result("error", query_text)
            if response.status_code != 200:
                return _empty_result("error", query_text)
            try:
                payload = response.json()
            except (TypeError, ValueError):
                return _empty_result("error", query_text)
            if not isinstance(payload, list):
                return _empty_result("error", query_text)

            accepted = []
            for candidate in payload:
                if not isinstance(candidate, dict):
                    continue
                validation = self._valid_candidate(candidate, kind, components)
                if validation is not None:
                    accepted.append((validation[2], validation, candidate))

            if not accepted:
                result = _empty_result("not_found", query_text)
                self._store(cache_key, result, NOT_FOUND_TTL_SECONDS)
                return result

            _, validation, candidate = max(accepted, key=lambda item: item[0])
            confidence = {"street": 0.95, "neighborhood": 0.85, "city": 0.70}[kind]
            result = {
                "latitude": validation[0],
                "longitude": validation[1],
                "display_name": candidate.get("display_name"),
                "query": query_text,
                "confidence": confidence,
                "precision": kind,
                "status": "resolved",
            }
            self._store(cache_key, result, RESOLVED_TTL_SECONDS)
            return result

    def geocode(self, location: dict) -> dict:
        """Resolve an extracted location using component-priority fallbacks."""
        if not self.base_url or not self.user_agent:
            return _empty_result("skipped")
        if not isinstance(location, dict):
            return _empty_result("skipped")
        try:
            extraction_confidence = float(location.get("confidence", 0.0))
        except (TypeError, ValueError):
            return _empty_result("skipped")
        city = location.get("city")
        if extraction_confidence < MIN_LOCATION_CONFIDENCE or not city:
            return _empty_result("skipped")

        components = {"city": city}
        attempts = []
        if location.get("street"):
            attempts.append(("street", {**components, "street": location["street"]}))
        if location.get("neighborhood"):
            attempts.append(
                (
                    "neighborhood",
                    {**components, "neighborhood": location["neighborhood"]},
                )
            )
        attempts.append(("city", components))

        last_not_found = None
        for kind, query_components in attempts:
            result = self._request(kind, query_components)
            if result["status"] == "resolved":
                return result
            if result["status"] == "error":
                return result
            last_not_found = result
        return last_not_found or _empty_result("not_found")


_default_geocoder: NominatimGeocoder | None = None


def geocode_fire_location(location: dict) -> dict:
    """Geocode with a lazily constructed process-wide default service."""
    global _default_geocoder
    if _default_geocoder is None:
        _default_geocoder = NominatimGeocoder()
    return _default_geocoder.geocode(location)
