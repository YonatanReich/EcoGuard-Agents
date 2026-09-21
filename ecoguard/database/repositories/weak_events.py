"""Storing uncorroborated reports and the outcomes they reach."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from ecoguard.database.engine import Session

OPEN = "open"
PROMOTED = "promoted"
UNCONFIRMED = "unconfirmed"
DISMISSED = "dismissed"
CONFIRMED = "confirmed"


def next_weak_event_id(at: datetime) -> str:
    """WEAK-20260921-0003. Same readable shape as an incident id, different
    prefix, because an operator saying one aloud must not be heard as the
    other."""
    day = at.astimezone(timezone.utc).strftime("%Y%m%d")
    with Session() as session:
        used = session.execute(
            text("SELECT count(*) FROM weak_events WHERE id LIKE :prefix"),
            {"prefix": f"WEAK-{day}-%"},
        ).scalar_one()
    return f"WEAK-{day}-{used + 1:04d}"


def _report_json(report: Any) -> dict[str, Any]:
    record = asdict(report) if is_dataclass(report) else dict(report)
    observed_at = record.get("observed_at")
    if isinstance(observed_at, datetime):
        record["observed_at"] = observed_at.isoformat()
    return record


def open_weak_events(hazard: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM weak_events WHERE status = 'open'"
    params: dict[str, Any] = {}
    if hazard is not None:
        query += " AND hazard = :hazard"
        params["hazard"] = hazard
    query += " ORDER BY last_seen_at DESC"
    with Session() as session:
        return [dict(row) for row in session.execute(text(query), params).mappings()]


def save_weak_event(weak: Mapping[str, Any], *, at: datetime | None = None) -> str:
    """Insert a new weak event, or add reports to one already open."""
    now = at or datetime.now(timezone.utc)
    reports = [_report_json(report) for report in weak.get("reports") or ()]

    if weak.get("id"):
        with Session() as session:
            session.execute(
                text(
                    """
                    UPDATE weak_events
                       SET last_seen_at = :last_seen_at,
                           reports = reports || CAST(:reports AS jsonb)
                     WHERE id = :id
                    """
                ),
                {
                    "id": weak["id"],
                    "last_seen_at": weak["last_seen_at"],
                    "reports": json.dumps(reports, ensure_ascii=False),
                },
            )
            session.commit()
        return weak["id"]

    weak_id = next_weak_event_id(now)
    with Session() as session:
        session.execute(
            text(
                """
                INSERT INTO weak_events (
                  id, hazard, status, cell_id, latitude, longitude,
                  precision_m, location_text, first_seen_at, last_seen_at,
                  expires_at, reports
                ) VALUES (
                  :id, :hazard, 'open', :cell_id, :latitude, :longitude,
                  :precision_m, :location_text, :first_seen_at, :last_seen_at,
                  :expires_at, CAST(:reports AS jsonb)
                )
                """
            ),
            {
                "id": weak_id,
                "hazard": weak["hazard"],
                "cell_id": weak.get("cell_id"),
                "latitude": weak.get("latitude"),
                "longitude": weak.get("longitude"),
                "precision_m": weak.get("precision_m"),
                "location_text": weak.get("location_text"),
                "first_seen_at": weak["first_seen_at"],
                "last_seen_at": weak["last_seen_at"],
                "expires_at": weak["expires_at"],
                "reports": json.dumps(reports, ensure_ascii=False),
            },
        )
        session.commit()
    return weak_id


def resolve_weak_event(
    weak_id: str,
    *,
    status: str,
    resolution: str,
    incident_id: str | None = None,
    operator: str | None = None,
    at: datetime | None = None,
) -> None:
    """End a weak event's life, recording which way and why.

    Nothing is deleted. A channel whose reports are never corroborated is a
    channel to drop, and §7 asks for exactly that review — which is only
    possible if the misses are still here to count.
    """
    with Session() as session:
        session.execute(
            text(
                """
                UPDATE weak_events
                   SET status = :status,
                       resolution = :resolution,
                       incident_id = :incident_id,
                       confirmed_by = COALESCE(:operator, confirmed_by),
                       confirmed_at = CASE WHEN :operator IS NOT NULL
                                           THEN :at ELSE confirmed_at END,
                       resolved_at = :at
                 WHERE id = :id
                """
            ),
            {
                "id": weak_id,
                "status": status,
                "resolution": resolution,
                "incident_id": incident_id,
                "operator": operator,
                "at": at or datetime.now(timezone.utc),
            },
        )
        session.commit()


def expire_weak_events(ids: Sequence[str], *, at: datetime | None = None) -> int:
    """Mark the ones whose window passed with nothing agreeing."""
    if not ids:
        return 0
    with Session() as session:
        result = session.execute(
            text(
                """
                UPDATE weak_events
                   SET status = 'unconfirmed',
                       resolution = 'expired_without_corroboration',
                       resolved_at = :at
                 WHERE id = ANY(:ids) AND status = 'open'
                """
            ),
            {"ids": list(ids), "at": at or datetime.now(timezone.utc)},
        )
        session.commit()
    return result.rowcount or 0
