"""Durable, incident-keyed SharedEvent projection repository."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session


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
    with Session() as session:
        row = session.execute(
            text(
                "SELECT * FROM event_projections WHERE incident_id = :incident_id"
            ),
            {"incident_id": incident_id},
        ).mappings().first()
    return dict(row) if row else None


def projected_events(*, limit: int = 100) -> list[dict[str, Any]]:
    """Newest projectable incidents, with a deterministic identity tie-break."""

    if not 1 <= limit <= 200:
        raise ValueError("event projection limit must be between 1 and 200")

    with Session() as session:
        rows = session.execute(
            text(
                "SELECT * FROM event_projections "
                "WHERE (event_payload IS NOT NULL "
                "   OR last_successful_event_payload IS NOT NULL) "
                "ORDER BY updated_at DESC, incident_id ASC LIMIT :limit"
            ),
            {"limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]
