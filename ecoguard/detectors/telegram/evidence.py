"""Enrich existing Fire/Flood signals with matched Telegram evidence.

This module never creates a signal. Its public function has a strict one-input /
one-output invariant and returns the original objects unchanged if evidence
processing fails.
"""

from __future__ import annotations

from ecoguard.shared.activity import live_actor

import hashlib
import logging
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Sequence

from ecoguard.collection.shared.telegram.policy import policy_for_username
from ecoguard.database.repositories.telegram_observations import (
    recent_telegram_observations,
)
from ecoguard.database.repositories.towns import (
    NamedTownLookupResult,
    TownLookupStatus,
    resolve_named_town,
)
from ecoguard.detectors.fire.hebrew_location_extractor import (
    extract_location,
    locality_name_candidates,
)
from ecoguard.detectors.fire.telegram_candidate_filter import detect_fire_candidate
from ecoguard.detectors.telegram.contracts import (
    TelegramEvidenceResult,
    TelegramExtractedLocation,
    TelegramMessageReference,
)
from ecoguard.detectors.telegram.flood_candidate_filter import detect_flood_candidate
from ecoguard.shared.cells import are_adjacent, cell_by_id, cell_for
from ecoguard.shared.geocoding import geocode_fire_location
from ecoguard.shared.signals import CORROBORATION_WINDOW, FIRE, FLOOD, CellSignal


logger = logging.getLogger(__name__)
SUPPORTED_HAZARDS = frozenset({FIRE, FLOOD})
STRUCTURED_SOURCES = {
    FIRE: frozenset({"firms"}),
    FLOOD: frozenset({"water_authority_hydrometric_observations"}),
}
DEFAULT_FLOOD_WINDOW_MINUTES = 90
MAX_TELEGRAM_ROWS = 1000
TOWN_PROXIMITY_METRES = 7_500.0

ObservationReader = Callable[..., list[dict[str, Any]]]
Geocoder = Callable[[dict[str, Any]], dict[str, Any]]
TownResolver = Callable[..., NamedTownLookupResult]
Clock = Callable[[], datetime]


def flood_corroboration_window() -> timedelta:
    raw = os.getenv(
        "TELEGRAM_FLOOD_CORROBORATION_WINDOW_MINUTES",
        str(DEFAULT_FLOOD_WINDOW_MINUTES),
    )
    try:
        minutes = int(raw)
    except ValueError as error:
        raise RuntimeError(
            "TELEGRAM_FLOOD_CORROBORATION_WINDOW_MINUTES must be an integer"
        ) from error
    if not 1 <= minutes <= 24 * 60:
        raise RuntimeError(
            "TELEGRAM_FLOOD_CORROBORATION_WINDOW_MINUTES must be between 1 and 1440"
        )
    return timedelta(minutes=minutes)


def _window_for(hazard: str) -> timedelta:
    return CORROBORATION_WINDOW if hazard == FIRE else flood_corroboration_window()


def _eligible(signal: CellSignal) -> bool:
    return (
        signal.hazard in SUPPORTED_HAZARDS
        and signal.source in STRUCTURED_SOURCES[signal.hazard]
    )


def _candidate(text: str) -> tuple[str | None, float, list[str]]:
    fire = detect_fire_candidate(text)
    flood = detect_flood_candidate(text)
    fire_matches = bool(fire["is_fire_candidate"])
    flood_matches = bool(flood["is_flood_candidate"])
    if fire_matches and flood_matches:
        return (
            "ambiguous",
            max(float(fire["confidence"]), float(flood["confidence"])),
            list(dict.fromkeys([*fire["matched_terms"], *flood["matched_terms"]])),
        )
    if fire_matches:
        return "fire", float(fire["confidence"]), list(fire["matched_terms"])
    if flood_matches:
        return "flood", float(flood["confidence"]), list(flood["matched_terms"])
    return None, 0.0, []


def _message_fingerprint(payload: dict[str, Any], text: str) -> str:
    forwarded = payload.get("forwarded_provenance") or {}
    if forwarded.get("origin_peer_id") is not None and forwarded.get(
        "origin_message_id"
    ) is not None:
        material = (
            f"forward:{forwarded['origin_peer_id']}:"
            f"{forwarded['origin_message_id']}"
        )
    else:
        material = " ".join(text.casefold().split())
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _source_verification(payload: dict[str, Any]) -> tuple[dict[str, Any], bool, list[str]]:
    username = payload.get("configured_username") or payload.get("channel_username")
    policy = policy_for_username(username)
    limitations: list[str] = []
    if policy is None:
        return {
            "tier": "unconfigured",
            "role": "unknown",
            "peer_id_pinned": False,
            "peer_id_verified": False,
            "event_verified": False,
        }, False, ["channel_not_in_configured_policy"]
    try:
        peer_id = int(payload["peer_id"])
    except (KeyError, TypeError, ValueError):
        return policy.verification(0), False, ["stable_peer_id_missing"]
    resolved_username = payload.get("channel_username")
    username_matches = (
        isinstance(resolved_username, str)
        and resolved_username.casefold() == policy.username.casefold()
    )
    verification = policy.verification(peer_id)
    accepted = bool(verification["peer_id_verified"] and username_matches)
    if not verification["peer_id_pinned"]:
        limitations.append("channel_peer_id_not_pinned")
    elif not verification["peer_id_verified"]:
        limitations.append("channel_peer_id_did_not_match_pin")
    if not username_matches:
        limitations.append("resolved_username_did_not_match_policy")
    if policy.role == "unofficial_aggregator":
        limitations.append("unofficial_aggregator_is_not_authoritative")
    return verification, accepted, limitations


def _extract_and_geocode(
    text: str,
    *,
    hazard: str,
    signal: CellSignal,
    geocoder: Geocoder,
    town_resolver: TownResolver,
) -> tuple[TelegramExtractedLocation, str | None, str, bool, list[str]]:
    signal_cell = cell_by_id(signal.cell_id)
    signal_latitude = signal.location.latitude if signal.location else (
        signal_cell.latitude if signal_cell else None
    )
    signal_longitude = signal.location.longitude if signal.location else (
        signal_cell.longitude if signal_cell else None
    )
    candidates = locality_name_candidates(text)
    if signal_latitude is not None and signal_longitude is not None and candidates:
        try:
            town_result = town_resolver(
                candidate_names=candidates,
                latitude=signal_latitude,
                longitude=signal_longitude,
            )
        except Exception:
            logger.exception("Shared towns locality resolution failed; using fallback")
            town_result = NamedTownLookupResult(
                status=TownLookupStatus.UNAVAILABLE,
                reason="town_repository_unavailable",
            )
        if (
            town_result.status == TownLookupStatus.SUCCESS_WITH_RESULTS
            and town_result.match is not None
        ):
            town = town_result.match
            precision = (
                "municipality"
                if town.outline_source == "municipal boundary"
                else "locality"
            )
            relation = (
                "inside_locality"
                if town.contains_signal
                else "near_locality"
                if town.distance_m <= TOWN_PROXIMITY_METRES
                else "distant"
            )
            limitations = ["town_outline_is_not_an_exact_incident_location"]
            if precision == "municipality":
                limitations.append("municipal_boundary_may_include_open_land")
            return TelegramExtractedLocation(
                location_text=town.name_he,
                city=town.name_he,
                street=None,
                neighborhood=None,
                latitude=None,
                longitude=None,
                cell_id=None,
                extraction_confidence=0.90,
                geocode_confidence=1.0,
                geocode_status="resolved_shared_postgis_town",
                resolver=town_result.source,
                town_id=town.town_id,
                town_outline_source=town.outline_source,
                town_distance_m=town.distance_m,
            ), precision, relation, relation in {"inside_locality", "near_locality"}, limitations

    extracted = extract_location(text, event_type=hazard)
    limitations: list[str] = []
    try:
        geocoded = geocoder(extracted)
    except Exception:
        geocoded = {
            "status": "error", "latitude": None, "longitude": None,
            "confidence": 0.0, "precision": None,
        }
        limitations.append("geocoding_failed")
    latitude = geocoded.get("latitude")
    longitude = geocoded.get("longitude")
    resolved_cell = (
        cell_for(float(latitude), float(longitude))
        if latitude is not None and longitude is not None
        else None
    )
    precision = geocoded.get("precision")
    if precision == "city":
        limitations.append("locality_centroid_is_not_an_exact_incident_location")
    if resolved_cell is None:
        limitations.append("telegram_location_not_resolved_to_service_area")
    relation = "unresolved"
    if resolved_cell == signal.cell_id:
        relation = "same_cell"
    elif resolved_cell is not None and are_adjacent(resolved_cell, signal.cell_id):
        relation = "adjacent_cell"
    elif resolved_cell is not None:
        relation = "distant"
    return TelegramExtractedLocation(
        location_text=extracted.get("location_text"),
        city=extracted.get("city"),
        street=extracted.get("street"),
        neighborhood=extracted.get("neighborhood"),
        latitude=float(latitude) if latitude is not None else None,
        longitude=float(longitude) if longitude is not None else None,
        cell_id=resolved_cell,
        extraction_confidence=float(extracted.get("confidence") or 0.0),
        geocode_confidence=float(geocoded.get("confidence") or 0.0),
        geocode_status=str(geocoded.get("status") or "unresolved"),
    ), precision, relation, relation in {"same_cell", "adjacent_cell"}, limitations


def _result_for(
    signal: CellSignal,
    row: dict[str, Any],
    *,
    checked_at: datetime,
    geocoder: Geocoder,
    town_resolver: TownResolver,
    duplicate: bool,
) -> TelegramEvidenceResult | None:
    payload = row.get("payload") or {}
    text = payload.get("raw_text") or payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    candidate_type, candidate_confidence, _ = _candidate(text)
    if candidate_type is None:
        return None

    observed_at = row.get("observed_at")
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise ValueError("persisted Telegram observed_at must carry a UTC offset")
    observed_at = observed_at.astimezone(timezone.utc)
    verification, source_accepted, limitations = _source_verification(payload)
    extracted, precision, relation, geography_matches, location_limits = _extract_and_geocode(
        text,
        hazard=signal.hazard,
        signal=signal,
        geocoder=geocoder,
        town_resolver=town_resolver,
    )
    limitations.extend(location_limits)

    time_gap = abs((signal.observed_at - observed_at).total_seconds())
    event_type_matches = candidate_type == signal.hazard
    temporal_matches = time_gap <= _window_for(signal.hazard).total_seconds()
    rules = {
        "event_type": event_type_matches,
        "source_policy": source_accepted,
        "temporal_proximity": temporal_matches,
        "geographic_proximity": geography_matches,
        "independent_message": not duplicate,
    }
    supporting = all(rules.values())
    if duplicate:
        limitations.append("duplicate_or_forwarded_copy_not_counted_as_independent_support")

    peer_id = int(payload.get("peer_id") or 0)
    message_id = int(payload.get("message_id") or 0)
    return TelegramEvidenceResult(
        status="SUPPORTING" if supporting else "UNMATCHED",
        checked_at=checked_at,
        signal_hazard=signal.hazard,
        message_reference=TelegramMessageReference(
            observation_id=int(row["id"]) if row.get("id") is not None else None,
            peer_id=peer_id,
            configured_username=str(
                payload.get("configured_username") or payload.get("channel_username") or "unknown"
            ),
            channel_title=payload.get("channel_title"),
            message_id=message_id,
            posted_at=observed_at,
            edited_at=payload.get("edited_at"),
            source_url=payload.get("source_url"),
            forwarded_provenance=payload.get("forwarded_provenance"),
        ),
        source_verification=verification,
        candidate_event_type=candidate_type,
        candidate_confidence=candidate_confidence,
        extracted_location=extracted,
        location_precision=precision,
        cell_relation=relation,
        time_gap_seconds=time_gap,
        matched_rules=[name for name, matched in rules.items() if matched],
        failed_rules=[name for name, matched in rules.items() if not matched],
        limitations=list(dict.fromkeys(limitations)),
    )


def _enrich(
    signals: Sequence[CellSignal],
    *,
    observation_reader: ObservationReader,
    geocoder: Geocoder,
    town_resolver: TownResolver,
    clock: Clock,
) -> list[CellSignal]:
    eligible = [signal for signal in signals if _eligible(signal)]
    if not eligible:
        return list(signals)
    maximum_window = max(_window_for(signal.hazard) for signal in eligible)
    rows = observation_reader(
        observed_since=min(signal.observed_at for signal in eligible) - maximum_window,
        observed_through=max(signal.observed_at for signal in eligible) + maximum_window,
        limit=MAX_TELEGRAM_ROWS,
    )
    checked_at = clock().astimezone(timezone.utc)
    output: list[CellSignal] = []
    for signal in signals:
        if not _eligible(signal):
            output.append(signal)
            continue
        results: list[TelegramEvidenceResult] = []
        fingerprints: set[str] = set()
        for row in rows:
            payload = row.get("payload") or {}
            text = payload.get("raw_text") or payload.get("text")
            if not isinstance(text, str):
                continue
            fingerprint = _message_fingerprint(payload, text)
            duplicate = fingerprint in fingerprints
            result = _result_for(
                signal,
                row,
                checked_at=checked_at,
                geocoder=geocoder,
                town_resolver=town_resolver,
                duplicate=duplicate,
            )
            if result is not None:
                results.append(result)
                fingerprints.add(fingerprint)
        evidence = dict(signal.evidence)
        evidence["telegram_evidence"] = {
            "checked_at": checked_at.isoformat(),
            "statuses_emitted": ["SUPPORTING", "UNMATCHED"],
            "supporting_count": sum(result.status == "SUPPORTING" for result in results),
            "results": [result.as_json() for result in results],
        }
        output.append(replace(signal, evidence=evidence))
    return output


@live_actor("detector.telegram_evidence")
def enrich_signals_with_telegram(
    signals: Sequence[CellSignal],
    *,
    observation_reader: ObservationReader = recent_telegram_observations,
    geocoder: Geocoder = geocode_fire_location,
    town_resolver: TownResolver = resolve_named_town,
    clock: Clock = lambda: datetime.now(timezone.utc),
) -> list[CellSignal]:
    """Return exactly one output per input; fail open with original objects."""
    if not signals:
        return []
    try:
        output = _enrich(
            signals,
            observation_reader=observation_reader,
            geocoder=geocoder,
            town_resolver=town_resolver,
            clock=clock,
        )
        if len(output) != len(signals):
            raise RuntimeError("Telegram enrichment violated one-input/one-output")
        return output
    except Exception:
        logger.exception("Telegram evidence enrichment failed; forwarding original signals")
        return list(signals)
