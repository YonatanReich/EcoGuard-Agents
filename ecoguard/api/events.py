"""Read-only delivery API for durable shared event projections."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import TypeAdapter, ValidationError

from ecoguard.analyzers.non_emergency.air_pollution.event_qualification import (
    MatchingOfficialPollutantIndex,
    ProjectedAirPollutionIdentity,
    qualify_air_pollution_event,
)
from ecoguard.analyzers.non_emergency.air_pollution.official_classification import (
    classify_official_pollutant_sub_index,
)
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
_manual_test_feed = SharedEventFeed(events=[])


def manual_flood_test_enabled() -> bool:
    return os.getenv("ECOGUARD_MANUAL_FLOOD_TEST", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def set_manual_test_feed(feed: SharedEventFeed) -> None:
    """Replace the in-memory feed used only in explicit manual-test mode."""

    global _manual_test_feed
    _manual_test_feed = feed


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


def air_pollution_event_is_qualified(
    row: Mapping[str, Any],
    event: AirPollutionSharedEvent,
) -> bool:
    """Apply the two authoritative Air Pollution publication paths."""

    index = event.details.ministry_aqi
    decision = qualify_air_pollution_event(
        row,
        projected=ProjectedAirPollutionIdentity(
            station_id=event.details.station.id,
            channel_id=event.details.station.channel_id or "",
            pollutant=event.details.pollutant,
            observed_at=event.details.observation_timestamp,
            provider=event.details.station.provider,
        ),
        official_index=(
            MatchingOfficialPollutantIndex(
                station_id=index.station_id,
                channel_id=index.resolved_channel_id,
                pollutant=index.pollutant,
                pollutant_sub_index=index.pollutant_sub_index,
            )
            if index is not None
            else None
        ),
    )
    return decision.qualified


def air_pollution_event_is_publishable(event: AirPollutionSharedEvent) -> bool:
    """Apply EA-371 official pollutant display policy after qualification."""

    index = event.details.ministry_aqi
    classification = classify_official_pollutant_sub_index(
        pollutant=event.details.pollutant,
        pollutant_sub_index=(
            index.pollutant_sub_index
            if index is not None
            and index.station_id == event.details.station.id
            and index.resolved_channel_id == event.details.station.channel_id
            and index.pollutant == event.details.pollutant
            else None
        ),
    )
    return classification.classification in {"MODERATE", "LOW", "VERY_LOW"}


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
            if (
                isinstance(event, AirPollutionSharedEvent)
                and (
                    not air_pollution_event_is_qualified(row, event)
                    or not air_pollution_event_is_publishable(event)
                )
            ):
                continue
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


    try:
        return shared_event_feed(read_projected_events(limit=limit))
    except Exception as error:
        logger.exception("Unable to read durable event projections")
        raise HTTPException(status_code=503, detail="Event feed is unavailable") from error
