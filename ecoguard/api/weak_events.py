"""Reports nothing has corroborated, as the operator sees them.

Served on their own route rather than mixed into the main feed. Everything
downstream of an event assumes it is believed to be happening; one of these is
not, and a separate shape is the only way to say so that cannot be lost by
forgetting to check a flag."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ecoguard.database.repositories import weak_events as store
from ecoguard.database.repositories.text_sources import OFFICIAL_TIERS

logger = logging.getLogger(__name__)

router = APIRouter()


class WeakEventReport(BaseModel):
    """One message behind a weak event — who said it, and when."""

    source_id: str
    tier: str
    claim: str | None = None
    location_text: str | None = None
    observed_at: datetime | None = None


class WeakEvent(BaseModel):
    """A report nobody has corroborated. Deliberately not a SharedEvent."""

    id: str
    hazard: Literal["fire", "flood", "earthquake", "air_quality"]
    status: str
    latitude: float | None = None
    longitude: float | None = None
    precision_m: float | None = None
    location_text: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    # What the card counts down. Negative means the sweep has not run yet, and
    # is shown as expiring rather than as a negative number.
    expires_in_seconds: int
    reports: list[WeakEventReport] = Field(default_factory=list)
    # What would turn this into an event, spelled out for the operator rather
    # than left as tribal knowledge about §4.
    would_confirm: list[str] = Field(default_factory=list)


class WeakEventFeed(BaseModel):
    weak_events: list[WeakEvent]


class OperatorDecision(BaseModel):
    """Who decided, so the record says more than "somebody clicked"."""

    operator: str = Field(min_length=1, max_length=200)


def _would_confirm(hazard: str) -> list[str]:
    """What evidence would turn this report into a confirmed event."""
    instrument = {
        "fire": "a satellite hotspot in the same area",
        "flood": "a gauge or rainfall exceedance in the same area",
        "earthquake": "a seismic event in the same area",
        "air_quality": "a monitoring station exceedance in the same area",
    }
    return [
        "a report from an authority or an established outlet",
        "a second independent report, from a different origin",
        instrument.get(hazard, "instrument data in the same area"),
    ]


def as_weak_event(row: dict[str, Any], *, now: datetime) -> WeakEvent:
    """One stored row in the shape the operator's list reads."""
    reports = []
    for report in row.get("reports") or ():
        if not isinstance(report, dict):
            continue
        reports.append(WeakEventReport(
            source_id=str(report.get("source_id") or "unknown"),
            tier=str(report.get("tier") or "unofficial"),
            claim=report.get("claim"),
            location_text=report.get("location_text"),
            observed_at=report.get("observed_at"),
        ))
    expires_at = row["expires_at"]
    return WeakEvent(
        id=row["id"],
        hazard=row["hazard"],
        status=row["status"],
        latitude=row.get("latitude"),
        longitude=row.get("longitude"),
        precision_m=row.get("precision_m"),
        location_text=row.get("location_text"),
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        expires_at=expires_at,
        expires_in_seconds=int((expires_at - now).total_seconds()),
        reports=reports,
        would_confirm=_would_confirm(row["hazard"]),
    )


@router.get("/api/weak-events", response_model=WeakEventFeed)
def get_weak_events() -> WeakEventFeed:
    """Every uncorroborated report currently on the map."""
    now = datetime.now(timezone.utc)
    try:
        rows = store.open_weak_events()
    except Exception as error:
        logger.exception("Unable to read weak events")
        raise HTTPException(
            status_code=503, detail="Weak event feed is unavailable"
        ) from error
    return WeakEventFeed(weak_events=[as_weak_event(row, now=now) for row in rows])


@router.post("/api/weak-events/{weak_event_id}/confirm", response_model=WeakEvent)
def confirm_weak_event(weak_event_id: str, decision: OperatorDecision) -> WeakEvent:
    """An operator vouches for a report. §4: this counts as an official source.

    It does not itself create the incident. The next triage pass reads a
    confirmed weak event exactly as it reads an authority report, so promotion
    goes through the one path that already knows how to dedup — rather than a
    second, hand-written one that would drift from it.
    """
    return _decide(
        weak_event_id,
        status=store.CONFIRMED,
        resolution=f"confirmed_by_operator:{decision.operator}",
        operator=decision.operator,
    )


@router.post("/api/weak-events/{weak_event_id}/dismiss", response_model=WeakEvent)
def dismiss_weak_event(weak_event_id: str, decision: OperatorDecision) -> WeakEvent:
    """An operator says no. The row stays, marked, for the monthly source review."""
    return _decide(
        weak_event_id,
        status=store.DISMISSED,
        resolution=f"dismissed_by_operator:{decision.operator}",
        operator=decision.operator,
    )


def _decide(
    weak_event_id: str, *, status: str, resolution: str, operator: str
) -> WeakEvent:
    """Record an operator's decision on one report."""
    now = datetime.now(timezone.utc)
    try:
        current = {row["id"]: row for row in store.open_weak_events()}
        row = current.get(weak_event_id)
        if row is None:
            # Either it never existed or somebody already decided. Both are a
            # 404 to a client holding a stale list, and neither should be
            # overwritten by a second click.
            raise HTTPException(status_code=404, detail="No open weak event with that id")
        store.resolve_weak_event(
            weak_event_id, status=status, resolution=resolution, operator=operator, at=now
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Unable to record operator decision on %s", weak_event_id)
        raise HTTPException(
            status_code=503, detail="Weak event store is unavailable"
        ) from error
    return as_weak_event({**row, "status": status}, now=now)


__all__ = ["router", "WeakEvent", "WeakEventFeed", "as_weak_event", "OFFICIAL_TIERS"]
