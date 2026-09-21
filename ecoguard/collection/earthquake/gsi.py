"""Minimal client for GSI's FDSN EVENT service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ecoguard.collection.base import BaseCollector
from ecoguard.shared.cells import cell_for

SOURCE = "gsi_earthquake"
PROVIDER = "GSI"
FDSN_EVENT_QUERY_URL = "https://seis.gsi.gov.il/fdsnws/event/1/query"

# GSI's FDSN text carries a 14th column, EventType, and most of what the
# service returns is not seismic: a sample week held 37 explosions to 8
# earthquakes, quarry blasts across the Negev. Ingesting those as
# earthquakes would put a magnitude 2.5 blast into the incident pipeline
# as ground shaking.
#
# A row with no label is kept. Absence of a label is not evidence the
# event was a blast, and missing a real earthquake is the worse error of
# the two. Anything GSI explicitly labels as something other than an
# earthquake is skipped, so a vocabulary we have not seen shows up as a
# drop in counts rather than as a fabricated earthquake.
EVENT_TYPE_COLUMN = 13



class GsiEarthquake(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_event_id: str
    observed_at: AwareDatetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    magnitude: float
    depth_km: float = Field(ge=0)
    provider: str = PROVIDER
    raw: dict[str, Any]


def normalize_fdsn_text(text_payload: str) -> list[GsiEarthquake]:
    """Normalize standard FDSN text rows without depending on a live request."""

    events: list[GsiEarthquake] = []
    for line in text_payload.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        columns = stripped.split("|")
        if len(columns) < 11:
            raise ValueError("invalid GSI FDSN event row")
        event_id, observed_at, latitude, longitude, depth_km = columns[:5]
        magnitude = columns[10]
        raw = {
            "event_id": event_id,
            "author": columns[5] or None,
            "catalog": columns[6] or None,
            "contributor": columns[7] or None,
            "contributor_id": columns[8] or None,
            "magnitude_type": columns[9] or None,
            "magnitude_author": columns[11] if len(columns) > 11 else None,
            "event_location_name": columns[12] if len(columns) > 12 else None,
        }
        event_type = ""
        if len(columns) > EVENT_TYPE_COLUMN:
            event_type = columns[EVENT_TYPE_COLUMN].strip().lower()
        if event_type and "earthquake" not in event_type:
            continue
        raw["event_type"] = event_type or None

        # FDSN text times are UTC by specification and GSI sends them with no
        # zone suffix, so attaching UTC reads the format rather than guessing
        # at it. Without this every live response fails validation on the
        # first row, which is why this collector had never completed a fetch.
        timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        events.append(GsiEarthquake(
            provider_event_id=event_id,
            observed_at=timestamp,
            latitude=float(latitude),
            longitude=float(longitude),
            magnitude=float(magnitude),
            depth_km=max(0.0, float(depth_km)),
            raw=raw,
        ))
    return events


class GsiEarthquakeCollector(BaseCollector):
    source = SOURCE

    def __init__(
        self,
        *,
        get: Callable[..., Any] = requests.get,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._get = get
        self._now = now

    def fetch(self) -> list[dict[str, Any]]:
        end = self._now().astimezone(timezone.utc)
        response = self._get(
            FDSN_EVENT_QUERY_URL,
            params={
                "format": "text",
                "starttime": (end - timedelta(days=7)).isoformat(),
                "endtime": end.isoformat(),
                "minlatitude": 28.0,
                "maxlatitude": 34.5,
                "minlongitude": 32.0,
                "maxlongitude": 36.5,
                "limit": 100,
                "orderby": "time",
            },
            timeout=20,
        )
        response.raise_for_status()

        records = []
        for event in normalize_fdsn_text(response.text):
            cell_id = cell_for(event.latitude, event.longitude)
            if cell_id is None:
                continue
            records.append({
                "cell_id": cell_id,
                "observed_at": event.observed_at,
                "latitude": event.latitude,
                "longitude": event.longitude,
                "payload": event.model_dump(mode="json"),
            })
        return records
