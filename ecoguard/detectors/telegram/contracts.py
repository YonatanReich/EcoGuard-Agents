"""Typed, JSON-safe Telegram evidence contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal


TelegramEvidenceStatus = Literal["SUPPORTING", "UNMATCHED", "CONFLICTING"]
TelegramCandidateEventType = Literal["fire", "flood", "ambiguous"]


@dataclass(frozen=True)
class TelegramMessageReference:
    observation_id: int | None
    peer_id: int
    configured_username: str
    channel_title: str | None
    message_id: int
    posted_at: datetime
    edited_at: str | None
    source_url: str | None
    forwarded_provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class TelegramExtractedLocation:
    location_text: str | None
    city: str | None
    street: str | None
    neighborhood: str | None
    latitude: float | None
    longitude: float | None
    cell_id: str | None
    extraction_confidence: float
    geocode_confidence: float
    geocode_status: str
    resolver: str | None = None
    town_id: str | None = None
    town_outline_source: str | None = None
    town_distance_m: float | None = None


@dataclass(frozen=True)
class TelegramEvidenceResult:
    status: TelegramEvidenceStatus
    checked_at: datetime
    signal_hazard: Literal["fire", "flood"]
    message_reference: TelegramMessageReference
    source_verification: dict[str, Any]
    candidate_event_type: TelegramCandidateEventType
    candidate_confidence: float
    extracted_location: TelegramExtractedLocation
    location_precision: str | None
    cell_relation: Literal[
        "same_cell", "adjacent_cell", "inside_locality", "near_locality",
        "distant", "unresolved"
    ]
    time_gap_seconds: float
    matched_rules: list[str] = field(default_factory=list)
    failed_rules: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checked_at"] = self.checked_at.isoformat()
        payload["message_reference"]["posted_at"] = (
            self.message_reference.posted_at.isoformat()
        )
        return payload
