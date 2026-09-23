"""The stored event for each incident, and the feed the dashboard reads.

A projection outlives the incident it describes, on purpose: it is what the
dashboard drew, kept so a closed event can still be looked up. That makes the
feed responsible for deciding what is current, which is what `projected_events`
does - otherwise the map shows every event the system has ever produced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session

# How long a closed incident stays on the map. Long enough that an operator
# watching one resolve sees it resolve rather than blink out between refreshes,
# short enough that it is gone by the next shift.
CLOSED_GRACE = timedelta(minutes=30)


@dataclass(frozen=True)
class EventProjectionWrite:
    incident_id: str
    hazard: str
    route: str
    processing_status: str
    analysis_status: str | None
    planner_status: str | None
    analysis_id: str | None
    coordinator_routing_id: str | None
    handler: str | None
    event_payload: dict[str, Any] | None
    failure_stage: str | None
    failure_reason: str | None
    retryable: bool
    successful: bool
    attempted_at: datetime
    processed_at: datetime


def upsert_event_projection(record: EventProjectionWrite) -> dict[str, Any] | None:
    """Store one latest attempt while preserving identity and prior success."""

    payload = json.dumps(record.event_payload) if record.event_payload is not None else None
    with Session() as session:
        session.execute(
            text(
                """
                INSERT INTO event_projections (
                  incident_id, hazard, route, processing_status,
                  analysis_status, planner_status, analysis_id,
                  coordinator_routing_id, handler, event_payload,
                  last_successful_event_payload, failure_stage, failure_reason,
                  retryable, attempt_count, last_attempt_at, last_success_at,
                  processed_at
                ) VALUES (
                  :incident_id, :hazard, :route, :processing_status,
                  :analysis_status, :planner_status, :analysis_id,
                  :coordinator_routing_id, :handler, CAST(:event_payload AS jsonb),
                  CASE WHEN :successful THEN CAST(:event_payload AS jsonb) END,
                  :failure_stage, :failure_reason, :retryable, 1,
                  :attempted_at, CASE WHEN :successful THEN :processed_at END,
                  :processed_at
                )
                ON CONFLICT (incident_id) DO UPDATE SET
                  hazard = EXCLUDED.hazard,
                  route = EXCLUDED.route,
                  processing_status = EXCLUDED.processing_status,
                  analysis_status = EXCLUDED.analysis_status,
                  planner_status = EXCLUDED.planner_status,
                  analysis_id = EXCLUDED.analysis_id,
                  coordinator_routing_id = EXCLUDED.coordinator_routing_id,
                  handler = EXCLUDED.handler,
                  event_payload = COALESCE(EXCLUDED.event_payload,
                                           event_projections.event_payload),
                  last_successful_event_payload = CASE
                    WHEN :successful THEN EXCLUDED.event_payload
                    ELSE event_projections.last_successful_event_payload
                  END,
                  failure_stage = EXCLUDED.failure_stage,
                  failure_reason = EXCLUDED.failure_reason,
                  retryable = EXCLUDED.retryable,
                  attempt_count = event_projections.attempt_count + 1,
                  last_attempt_at = EXCLUDED.last_attempt_at,
                  last_success_at = CASE
                    WHEN :successful THEN EXCLUDED.processed_at
                    ELSE event_projections.last_success_at
                  END,
                  processed_at = EXCLUDED.processed_at,
                  updated_at = now()
                """
            ),
            {
                "incident_id": record.incident_id,
                "hazard": record.hazard,
                "route": record.route,
                "processing_status": record.processing_status,
                "analysis_status": record.analysis_status,
                "planner_status": record.planner_status,
                "analysis_id": record.analysis_id,
                "coordinator_routing_id": record.coordinator_routing_id,
                "handler": record.handler,
                "event_payload": payload,
                "failure_stage": record.failure_stage,
                "failure_reason": record.failure_reason,
                "retryable": record.retryable,
                "successful": record.successful,
                "attempted_at": record.attempted_at,
                "processed_at": record.processed_at,
            },
        )
        session.commit()
    return event_projection_by_incident(record.incident_id)


def event_projection_by_incident(incident_id: str) -> dict[str, Any] | None:
    """The event built for one incident, or None when there is none."""
    with Session() as session:
        row = session.execute(
            text(
                "SELECT * FROM event_projections WHERE incident_id = :incident_id"
            ),
            {"incident_id": incident_id},
        ).mappings().first()
    return dict(row) if row else None


def projected_events(
    *, limit: int = 100, include_closed_for: timedelta = CLOSED_GRACE
) -> list[dict[str, Any]]:
    """What is happening now, newest first, with a deterministic tie-break.

    Closed incidents drop off. A projection outlives the incident it describes,
    so without this the map accumulated every fire the system had ever seen -
    eleven of them, ten closed, one quiet for thirty-five hours, all drawn as
    though they were burning.

    The grace window keeps an incident visible for a short while after it
    closes, because an operator watching a fire resolve should see it resolve
    rather than have it vanish between refreshes.
    """

    if not 1 <= limit <= 200:
        raise ValueError("event projection limit must be between 1 and 200")

    with Session() as session:
        rows = session.execute(
            text(
                "SELECT event_projections.*, "
                "       incidents.signals AS incident_signals, "
                "       incidents.status AS incident_status "
                "FROM event_projections "
                "JOIN incidents ON incidents.id = event_projections.incident_id "
                "WHERE (event_projections.event_payload IS NOT NULL "
                "   OR event_projections.last_successful_event_payload IS NOT NULL) "
                "  AND (incidents.status = 'open' "
                "   OR incidents.closed_at >= :closed_after) "
                "ORDER BY event_projections.updated_at DESC, "
                "         event_projections.incident_id ASC LIMIT :limit"
            ),
            {
                "limit": limit,
                "closed_after": datetime.now(timezone.utc) - include_closed_for,
            },
        ).mappings().all()
    return [dict(row) for row in rows]
