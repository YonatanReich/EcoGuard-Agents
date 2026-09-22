"""The text lane, end to end: candidates in, signals and weak events out.

Geocoding happens here rather than in the classifier, for the reason §5 gives:
a model asked for coordinates will supply plausible ones for a town it has
never heard of. The gazetteer either knows a place or does not, and when it
does not the report is skipped with a reason rather than placed at a guess.

Promotion emits a `CellSignal` and stops. The coordinator then does what it
does for every other detector — matches it to an open incident or starts one,
dedups it, routes it to a queue — so a promoted report becomes an incident by
the ordinary path and nothing downstream needs to know where it came from.
"""

from __future__ import annotations

from ecoguard.shared.activity import live_actor

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from ecoguard.database.repositories import weak_events as weak_store
from ecoguard.database.repositories.text_candidates import (
    mark_candidates_triaged,
    recent_candidates,
)
from ecoguard.detectors.fire.hebrew_location_extractor import locality_name_candidates
from ecoguard.detectors.text.keywords import HAZARDS
from ecoguard.detectors.text.triage import Report, origin_key, triage
from ecoguard.shared.cells import cell_for
from ecoguard.shared.signals import CellLocation, CellSignal

logger = logging.getLogger(__name__)

SOURCE = "text_triage"

# How far back to consider candidates on one run. Wider than the corroboration
# window so a report and the official statement that confirms it are both in
# the same pass even when they arrive either side of a tick boundary.
LOOKBACK = timedelta(hours=6)

# A text report is a claim, not a measurement. There is no rarity to compute —
# nobody has a baseline for "how often does someone say there is a fire here" —
# and leaving it None is the honest answer the CellSignal contract asks for.
TEXT_VARIABLE = "report"


def locate(
    location_text: str | None,
    *,
    town_resolver=None,
) -> tuple[float, float, float] | None:
    """A place name to a point and its uncertainty, or None.

    Uses the shared towns gazetteer, which validates a name against canonical
    settlements rather than accepting whatever the message said. A town outline
    is kilometres across, so the uncertainty it returns is large on purpose:
    the corroboration radius grows with it instead of pretending to a precision
    a town name cannot carry.
    """
    if not location_text or not location_text.strip():
        return None

    from ecoguard.database.repositories.towns import search_towns

    resolver = town_resolver or search_towns
    for candidate in locality_name_candidates(location_text) or [location_text]:
        try:
            matches = resolver(candidate, 1)
        except Exception:
            logger.exception("text triage: town lookup failed for %r", candidate)
            continue
        if not matches:
            continue
        town = matches[0]
        label = town.get("label") or {}
        if label.get("latitude") is None or label.get("longitude") is None:
            continue
        return (
            float(label["latitude"]),
            float(label["longitude"]),
            _uncertainty_m(town.get("area_km2")),
        )
    return None


# A town name locates an event to the town, not to a point in it. The radius of
# a circle with the same area is the honest reading of "somewhere in here", and
# it is what the corroboration window widens by — so two reports of one fire in
# a large municipality still meet, and two reports in different villages do not.
DEFAULT_TOWN_UNCERTAINTY_M = 3000.0


def _uncertainty_m(area_km2: Any) -> float:
    import math

    try:
        area = float(area_km2)
    except (TypeError, ValueError):
        return DEFAULT_TOWN_UNCERTAINTY_M
    if area <= 0:
        return DEFAULT_TOWN_UNCERTAINTY_M
    return math.sqrt(area / math.pi) * 1000.0


def reports_from_candidates(
    candidates: Sequence[dict[str, Any]],
    *,
    locator=locate,
) -> tuple[list[Report], list[dict[str, Any]]]:
    """Turn stored candidates into located reports; return the unplaceable too."""
    located: list[Report] = []
    unplaceable: list[dict[str, Any]] = []

    for candidate in candidates:
        payload = candidate.get("payload") or {}
        place = locator(candidate.get("location_text"))
        if place is None:
            unplaceable.append({
                "observation_id": candidate["observation_id"],
                "location_text": candidate.get("location_text"),
                "reason": "location_not_in_gazetteer",
            })
            continue
        latitude, longitude, precision_m = place
        located.append(Report(
            candidate_id=candidate["id"],
            observation_id=candidate["observation_id"],
            source_id=candidate["source_id"],
            tier=candidate["tier"],
            hazard=candidate["hazard"],
            observed_at=candidate["observed_at"],
            text=candidate.get("claim") or "",
            # Computed from the stored message rather than stored on the
            # candidate: the forward metadata belongs to the observation, and
            # copying it would mean two places to correct when a payload is
            # re-read.
            origin_key=origin_key({**payload, "source_id": candidate["source_id"]}),
            latitude=latitude,
            longitude=longitude,
            precision_m=precision_m,
            location_text=candidate.get("location_text"),
            update_type=candidate.get("update_type") or "new",
            claim=candidate.get("claim"),
        ))
    return located, unplaceable


def signal_from(report: Report, basis: dict[str, Any]) -> CellSignal | None:
    """A promoted or official report, as the signal the coordinator expects.

    `rarity` is None and stays None: a claim has no baseline, and inventing a
    number here would let a rumour outrank a measurement in any comparison that
    sorts on it.
    """
    cell_id = cell_for(report.latitude, report.longitude)
    if cell_id is None:
        return None
    return CellSignal(
        cell_id=cell_id,
        observed_at=report.observed_at,
        hazard=report.hazard,
        variable=TEXT_VARIABLE,
        value=1.0,
        unit="report",
        source=report.source_id,
        rarity=None,
        direction="high",
        location=CellLocation(
            latitude=report.latitude,
            longitude=report.longitude,
            precision_m=report.precision_m,
            method="text_report_gazetteer",
        ),
        # The reading here is a person's say-so. Officials are trusted to be
        # reporting something real; a promoted unofficial report is trusted
        # because something else agreed, and carries what agreed with it.
        confidence=1.0 if report.official else 0.7,
        evidence={
            "text_report": {
                "tier": report.tier,
                "source_id": report.source_id,
                "observation_id": report.observation_id,
                "claim": report.claim,
                "location_text": report.location_text,
                "basis": basis,
            }
        },
    )


@live_actor("detector.text_triage")
def run_text_triage(
    *, at: datetime | None = None, coordinate=None
) -> dict[str, Any]:
    """One pass: read candidates, triage, persist, hand signals to the coordinator."""
    now = at or datetime.now(timezone.utc)

    candidates: list[dict[str, Any]] = []
    for hazard in HAZARDS:
        candidates.extend(recent_candidates(hazard, at=now, window=LOOKBACK))

    reports, unplaceable = reports_from_candidates(candidates)
    open_weak = weak_store.open_weak_events()

    # A completed candidate remains useful as corroborating context, but must
    # not emit its own event again on every sweep. Reports already represented
    # by an open weak event are the exception: they are reconsidered until
    # corroboration arrives or the weak event expires.
    pending_ids = {
        int(candidate["id"])
        for candidate in candidates
        if candidate.get("triaged_at") is None
    }
    open_candidate_to_weak: dict[int, str] = {}
    for weak in open_weak:
        for stored_report in weak.get("reports") or ():
            candidate_id = stored_report.get("candidate_id")
            if candidate_id is not None:
                open_candidate_to_weak[int(candidate_id)] = str(weak["id"])
    primary_ids = pending_ids | set(open_candidate_to_weak)
    primary_reports = [report for report in reports if report.candidate_id in primary_ids]

    from ecoguard.coordinator import incidents as incident_store

    outcome = triage(
        primary_reports,
        supporting_reports=reports,
        open_incidents=incident_store.open_incidents(),
        open_weak_events=open_weak,
        at=now,
    )

    weak_store.expire_weak_events(outcome.expired, at=now)
    completed_without_coordinator: set[int] = set()
    for weak in outcome.weak_events:
        new_reports = [
            report for report in weak.get("reports") or ()
            if report.candidate_id in pending_ids
        ]
        if not new_reports:
            continue
        weak_store.save_weak_event({**weak, "reports": new_reports}, at=now)
        completed_without_coordinator.update(report.candidate_id for report in new_reports)

    signals = []
    signal_candidate_ids: list[int] = []
    promoted_weak_events: dict[str, str] = {}
    for entry in (*outcome.events, *outcome.promoted):
        signal = signal_from(entry["report"], entry["basis"])
        if signal is not None:
            signals.append(signal)
            signal_candidate_ids.append(entry["report"].candidate_id)
            weak_id = open_candidate_to_weak.get(entry["report"].candidate_id)
            if weak_id is not None and entry in outcome.promoted:
                promoted_weak_events[weak_id] = str(
                    entry["basis"].get("kind") or "corroborated"
                )
        elif entry["report"].candidate_id in pending_ids:
            completed_without_coordinator.add(entry["report"].candidate_id)

    observation_to_candidates: dict[int, set[int]] = {}
    for candidate in candidates:
        observation_to_candidates.setdefault(
            int(candidate["observation_id"]), set()
        ).add(int(candidate["id"]))
    for item in (*unplaceable, *outcome.skipped):
        completed_without_coordinator.update(
            observation_to_candidates.get(int(item["observation_id"]), set())
            & pending_ids
        )
    completed_without_coordinator.update(
        entry["report"].candidate_id
        for entry in outcome.closed
        if entry["report"].candidate_id in pending_ids
    )

    mark_candidates_triaged(completed_without_coordinator, at=now)

    coordinated = None
    if signals:
        if coordinate is None:
            from ecoguard.coordinator.agent import run as coordinate
        coordinated = coordinate(signals)
        mark_candidates_triaged(signal_candidate_ids, at=now)
        for weak_id, resolution in promoted_weak_events.items():
            weak_store.resolve_weak_event(
                weak_id,
                status=weak_store.PROMOTED,
                resolution=resolution,
                at=now,
            )

    logger.info(
        "text triage: %s events, %s promoted, %s weak, %s expired, %s unplaceable",
        len(outcome.events), len(outcome.promoted), len(outcome.weak_events),
        len(outcome.expired), len(unplaceable),
    )
    return {
        "events": len(outcome.events),
        "promoted": len(outcome.promoted),
        "weak_events": len(outcome.weak_events),
        "expired": len(outcome.expired),
        "closed": len(outcome.closed),
        "unplaceable": unplaceable,
        "skipped": outcome.skipped,
        "coordination": coordinated,
    }
