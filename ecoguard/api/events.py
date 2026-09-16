"""Read-only delivery API for durable shared event projections."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import TypeAdapter, ValidationError

from ecoguard.shared.events import (
    AirPollutionSharedEvent,
    ComponentUnavailableReason,
    EventProcessingMetadata,
    SharedEvent,
    SharedEventFeed,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_event_adapter = TypeAdapter(SharedEvent)


def read_projected_events(*, limit: int) -> list[dict[str, Any]]:
    """Lazy DB import keeps unrelated request-scoped API routes importable."""

    from ecoguard.database.repositories.event_projections import projected_events

    return projected_events(limit=limit)


def _fallback_air_pollution_event(
    event: AirPollutionSharedEvent,
) -> AirPollutionSharedEvent:
    """Never present recommendations from an older plan as freshly computed."""

    details = event.details.model_copy(update={
        "recommendations": [],
        "verified_references": [],
        "unavailable_components": [
            *event.details.unavailable_components,
            ComponentUnavailableReason(
                component="event_projection",
                reason="latest_projection_unavailable_using_prior_projectable_state",
            ),
        ],
    })
    return event.model_copy(update={
        "description": (
            "The latest processing attempt could not refresh this advisory. "
            "Measurement details are from the last projectable state."
        ),
        "details": details,
    })


def shared_event_feed(rows: Sequence[Mapping[str, Any]]) -> SharedEventFeed:
    """Validate stored payloads and add current delivery-processing metadata."""

    events = []
    for row in rows:
        try:
            current_payload = row.get("event_payload")
            fallback = (
                current_payload is None or row.get("failure_stage") == "projection"
            )
            payload = current_payload or row.get("last_successful_event_payload")
            if not isinstance(payload, Mapping):
                raise ValueError("missing_event_payload")
            event = _event_adapter.validate_python(payload)
            if event.id != str(row.get("incident_id")):
                raise ValueError("event_identity_mismatch")
            if fallback and isinstance(event, AirPollutionSharedEvent):
                event = _fallback_air_pollution_event(event)
            processing = EventProcessingMetadata(
                route=str(row["route"]),
                status=str(row["processing_status"]),
                failure_stage=row.get("failure_stage"),
                failure_reason=row.get("failure_reason"),
                retryable=bool(row.get("retryable")),
                attempt_count=int(row.get("attempt_count") or 1),
                last_attempt_at=row["last_attempt_at"],
                processed_at=row["processed_at"],
                using_last_successful_payload=fallback,
            )
            events.append(event.model_copy(update={"processing": processing}))
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            logger.warning(
                "Skipping unusable event projection %s: %s",
                row.get("incident_id"),
                type(error).__name__,
            )
    return SharedEventFeed(events=events)


@router.get("/api/events", response_model=SharedEventFeed)
def get_shared_events(
    limit: int = Query(default=100, ge=1, le=200),
) -> SharedEventFeed:
    """Return newest durable projections; no detection or analysis runs here."""

    try:
        return shared_event_feed(read_projected_events(limit=limit))
    except Exception as error:
        logger.exception("Unable to read durable event projections")
        raise HTTPException(status_code=503, detail="Event feed is unavailable") from error
