"""Read-only delivery API for durable shared event projections."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, TypeAdapter, ValidationError

from ecoguard.shared.signals import AIR_POLLUTION, corroborates
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
_aware_datetime_adapter = TypeAdapter(AwareDatetime)


@dataclass(frozen=True)
class _StoredCorroborationSignal:
    detection_id: str
    cell_id: str
    observed_at: datetime
    hazard: str
    source: str
    station_id: str
    channel_id: str
    pollutant: str


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


def _stored_air_pollution_signals(
    row: Mapping[str, Any],
) -> list[_StoredCorroborationSignal]:
    signals = row.get("incident_signals")
    if not isinstance(signals, list):
        return []

    stored = []
    for signal in signals:
        if not isinstance(signal, Mapping) or signal.get("hazard") != AIR_POLLUTION:
            continue
        evidence = signal.get("evidence")
        candidate = (
            evidence.get("correlation_candidate")
            if isinstance(evidence, Mapping)
            else None
        )
        anomaly = candidate.get("anomaly") if isinstance(candidate, Mapping) else None
        detection_id = anomaly.get("detection_id") if isinstance(anomaly, Mapping) else None
        try:
            if not isinstance(detection_id, str) or not detection_id:
                continue
            cell_id = signal["cell_id"]
            if not isinstance(cell_id, str) or not cell_id:
                continue
            source = signal["source"]
            station_id = anomaly["station_id"]
            channel_id = anomaly["channel_id"]
            pollutant = anomaly["pollutant"]
            if not all(
                isinstance(value, str) and value
                for value in (source, station_id, channel_id, pollutant)
            ):
                continue
            observed_at = _aware_datetime_adapter.validate_python(signal["observed_at"])
        except (KeyError, TypeError, ValueError, ValidationError):
            continue
        stored.append(_StoredCorroborationSignal(
            detection_id=detection_id,
            cell_id=cell_id,
            observed_at=observed_at,
            hazard=AIR_POLLUTION,
            source=source,
            station_id=station_id,
            channel_id=channel_id,
            pollutant=pollutant,
        ))
    return stored


def _corroborating_pairs(row: Mapping[str, Any]):
    """Yield distinct persisted signal pairs accepted by shared corroboration."""

    signals = _stored_air_pollution_signals(row)
    for first, second in combinations(signals, 2):
        if first.detection_id == second.detection_id:
            continue
        try:
            if corroborates(first, second):  # type: ignore[arg-type]
                yield first, second
        except (TypeError, ValueError):
            continue


def _matches_projected_anomaly(
    signal: _StoredCorroborationSignal,
    event: AirPollutionSharedEvent,
) -> bool:
    station = event.details.station
    return bool(
        signal.station_id == station.id
        and signal.channel_id == station.channel_id
        and signal.pollutant == event.details.pollutant
        and signal.observed_at == event.details.observation_timestamp
        and (station.provider is None or signal.source == station.provider)
    )


def _path_a_spatial_corroboration(
    row: Mapping[str, Any],
    event: AirPollutionSharedEvent,
) -> bool:
    return any(
        first.pollutant == second.pollutant == event.details.pollutant
        and (first.source, first.station_id) != (second.source, second.station_id)
        and any(
            _matches_projected_anomaly(signal, event)
            for signal in (first, second)
        )
        for first, second in _corroborating_pairs(row)
    )


def _path_b_persistence_with_official_aqi(
    row: Mapping[str, Any],
    event: AirPollutionSharedEvent,
) -> bool:
    index = event.details.ministry_aqi
    if (
        index is None
        or index.pollutant_sub_index >= 0
        or index.station_id is None
        or index.pollutant is None
        or index.resolved_channel_id is None
        or index.station_id != event.details.station.id
        or index.pollutant != event.details.pollutant
        or index.resolved_channel_id != event.details.station.channel_id
    ):
        return False

    for first, second in _corroborating_pairs(row):
        if (
            (first.source, first.station_id) == (second.source, second.station_id)
            and first.station_id == index.station_id
            and first.pollutant == second.pollutant == index.pollutant
            and first.observed_at != second.observed_at
            and index.resolved_channel_id in {first.channel_id, second.channel_id}
            and any(
                _matches_projected_anomaly(signal, event)
                for signal in (first, second)
            )
        ):
            return True
    return False


def air_pollution_event_is_qualified(
    row: Mapping[str, Any],
    event: AirPollutionSharedEvent,
) -> bool:
    """Apply the two authoritative Air Pollution publication paths."""

    return _path_a_spatial_corroboration(
        row, event
    ) or _path_b_persistence_with_official_aqi(row, event)


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
                and not air_pollution_event_is_qualified(row, event)
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
    include_resource_allocation_demo: bool = Query(default=False),
) -> SharedEventFeed:
    """Return durable projections and, when requested, one isolated demo event."""

    if include_resource_allocation_demo:
        try:
            from ecoguard.api.resource_allocation_demo import (
                resource_allocation_demo_event,
            )

            # The preview must remain usable even when the projection tables
            # are unavailable or have not been migrated in a local database.
            return SharedEventFeed(events=[resource_allocation_demo_event()])
        except Exception as error:
            logger.exception("Unable to build resource allocation demo")
            raise HTTPException(
                status_code=503,
                detail="Resource allocation demo is unavailable",
            ) from error

    try:
        return shared_event_feed(read_projected_events(limit=limit))
    except Exception as error:
        logger.exception("Unable to read durable event projections")
        raise HTTPException(status_code=503, detail="Event feed is unavailable") from error
