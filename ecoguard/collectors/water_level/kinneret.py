"""The Water Authority's daily Kinneret level.

One figure for the whole lake rather than a reading at a point, so unlike every
other source here its coordinates are where it gets drawn, not where it was
measured.

The provider republishes the whole series back to 1966 on every call, so a day
missed during an outage repairs itself on the next tick."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from ecoguard.collectors.base import BaseCollector
from ecoguard.shared.cells import cell_for

SOURCE = "kinneret_level"
CKAN_SEARCH_URL = "https://data.gov.il/api/3/action/datastore_search"
# Dataset "מפלס כנרת", published by the Israel Water Authority.
RESOURCE_ID = "2de7b543-e13d-4e7e-b4c8-56071bc4d3c8"

# The middle of the lake. The reading describes all of it; this is the point
# that decides which cell the row lands in and where a map draws it.
KINNERET_LATITUDE = 32.80
KINNERET_LONGITUDE = 35.59

# The provider writes a survey date with no offset. It is a local calendar
# day, so it is pinned to Israel time rather than read as UTC — the two or
# three hours would otherwise move every reading onto the day before.
SOURCE_TIMEZONE = ZoneInfo("Asia/Jerusalem")

# Enough for the thirty-day trend with a wide margin for the gaps the series
# actually has, and small enough to stay a single request.
FETCH_LIMIT = 400

# The lake has never been near either of these: the upper red line is -208.8
# and the black line -214.87. A value outside the envelope is a provider
# error, a unit change or a sign flip, and storing one would turn into a
# confident recommendation to pump water into a lake that does not need it.
MINIMUM_PLAUSIBLE_LEVEL_M = -230.0
MAXIMUM_PLAUSIBLE_LEVEL_M = -195.0

REQUEST_TIMEOUT_SECONDS = 20


class KinneretLevelError(ValueError):
    """The dataset returned a payload that cannot safely be stored."""


def _survey_date(value: Any) -> datetime:
    """The survey day as a date, rejecting anything that is not one."""
    if not isinstance(value, str) or not value.strip():
        raise KinneretLevelError("Survey_Date must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise KinneretLevelError(
            f"Survey_Date {value!r} is not an ISO timestamp"
        ) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SOURCE_TIMEZONE)
    return parsed.astimezone(timezone.utc)


def _level(value: Any) -> float:
    """The lake level as a number, rejecting anything that is not one."""
    if isinstance(value, bool):
        raise KinneretLevelError("Kinneret_Level must be numeric")
    try:
        level = float(value)
    except (TypeError, ValueError) as error:
        raise KinneretLevelError("Kinneret_Level must be numeric") from error
    if not math.isfinite(level):
        raise KinneretLevelError("Kinneret_Level must be finite")
    if not MINIMUM_PLAUSIBLE_LEVEL_M <= level <= MAXIMUM_PLAUSIBLE_LEVEL_M:
        raise KinneretLevelError(
            f"Kinneret_Level {level} is outside the plausible envelope "
            f"[{MINIMUM_PLAUSIBLE_LEVEL_M}, {MAXIMUM_PLAUSIBLE_LEVEL_M}]"
        )
    return level


def parse_kinneret_records(payload: Any) -> list[dict[str, Any]]:
    """Normalize a CKAN datastore_search body into observation records.

    Separate from the request so the shape of the provider's response can be
    tested without one. A malformed row fails the whole batch rather than
    being skipped: this feed is one number a day, so a row it cannot read is
    a change in the feed and not noise to route around.
    """

    if not isinstance(payload, Mapping):
        raise KinneretLevelError("response must be a JSON object")
    if payload.get("success") is not True:
        raise KinneretLevelError("datastore_search did not report success")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise KinneretLevelError("response carries no result object")
    records = result.get("records")
    if not isinstance(records, list) or not records:
        raise KinneretLevelError("response carries no records")

    cell_id = cell_for(KINNERET_LATITUDE, KINNERET_LONGITUDE)
    if cell_id is None:
        raise KinneretLevelError("the Kinneret is outside the service-area grid")

    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise KinneretLevelError("each record must be an object")
        observed_at = _survey_date(record.get("Survey_Date"))
        level = _level(record.get("Kinneret_Level"))
        rows.append(
            {
                "cell_id": cell_id,
                "observed_at": observed_at,
                "latitude": KINNERET_LATITUDE,
                "longitude": KINNERET_LONGITUDE,
                "payload": {
                    "level_m": level,
                    "survey_date": observed_at.date().isoformat(),
                    "source_url": f"{CKAN_SEARCH_URL}?resource_id={RESOURCE_ID}",
                },
            }
        )
    return rows


class KinneretLevelCollector(BaseCollector):
    """Fetch the recent Kinneret series; storing and logging are inherited."""

    source = SOURCE

    def __init__(self, *, get: Callable[..., Any] = requests.get) -> None:
        """Build the collector. The HTTP call is injectable for testing."""
        self._get = get

    def fetch(self) -> list[dict[str, Any]]:
        """The most recent published lake levels."""
        response = self._get(
            CKAN_SEARCH_URL,
            params={
                "resource_id": RESOURCE_ID,
                "limit": FETCH_LIMIT,
                # Sorted explicitly rather than trusting the natural _id order.
                # The resource is republished whole, so _id is a row number in
                # the latest upload and not a stable recency key.
                "sort": "Survey_Date desc",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return parse_kinneret_records(response.json())
