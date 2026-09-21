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
        timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
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
