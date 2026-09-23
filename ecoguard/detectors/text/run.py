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

# The classifier labels breathable-air reports `air_quality`, which is the
# right word for what a message describes. Everything downstream — the queues,
# the handler registry, the event mappers — calls that hazard `air_pollution`,
# and the coordinator refuses a hazard it cannot route:
#
#   coordinator: 'air_quality' is in neither EMERGENCY_HAZARDS nor
#   ADVISORY_HAZARDS
#
# So a Telegram report of heavy smoke was classified correctly, geocoded
# correctly, and then dropped on the floor. Translating here rather than
# renaming the label keeps the stored candidate faithful to what the model was
# asked, and gives corroboration the same hazard name the structured detectors
# use, so a smoke report and a pollution reading can meet.
HAZARD_ALIASES = {"air_quality": "air_pollution"}

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
    """How vague a town-sized location is, as a radius in metres."""
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
            hazard=HAZARD_ALIASES.get(candidate["hazard"], candidate["hazard"]),
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


def signal_from(
    report: Report, basis: dict[str, Any], *, corroborated: bool = True
) -> CellSignal | None:
    """A triaged report, as the signal the coordinator expects.

    `rarity` is None and stays None: a claim has no baseline, and inventing a
    number here would let a rumour outrank a measurement in any comparison that
    sorts on it.

    `corroborated` is carried in the evidence rather than encoded in the hazard
    or the route, so an incident that starts as one uncorroborated report and
    later gains a hotspot needs nothing rewritten — the new signal simply is not
    a text report, and the incident stops qualifying as uncorroborated. See
    ecoguard.coordinator.dispatcher.is_uncorroborated_report.
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
        # The reading here is a person's say-so. A corroborated report is
        # trusted because something else agreed with it and carries what
        # agreed; an uncorroborated one is carried at the lowest confidence in
        # the system, because that is exactly what it is worth.
        confidence=0.7 if corroborated else 0.3,
        evidence={
            "text_report": {
                "tier": report.tier,
                "source_id": report.source_id,
                "observation_id": report.observation_id,
                "claim": report.claim,
                "location_text": report.location_text,
                "corroborated": corroborated,
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

    # A candidate is triaged once. It stays readable as corroborating context
    # for anything that lands later, but it does not emit its own signal twice —
    # that re-emission, against a weak-event store that expired the report
    # before an operator saw it, is what produced 70 rows from 3 messages.
    pending_ids = {
        int(candidate["id"])
        for candidate in candidates
        if candidate.get("triaged_at") is None
    }
    primary_reports = [
        report for report in reports if report.candidate_id in pending_ids
    ]

    from ecoguard.coordinator import incidents as incident_store

    outcome = triage(
        primary_reports,
        supporting_reports=reports,
        open_incidents=incident_store.open_incidents(),
        at=now,
    )

    # Both kinds go to the coordinator. The difference travels in the signal's
    # evidence, not in whether it is sent: an uncorroborated report is still
    # something an operator must be told about, and the advisory planner is
    # what tells them who to phone about it.
    signals = []
    signal_candidate_ids: list[int] = []
    for entry in outcome.events:
        signal = signal_from(entry["report"], entry["basis"], corroborated=True)
        if signal is not None:
            signals.append(signal)
            signal_candidate_ids.append(entry["report"].candidate_id)
    for entry in outcome.uncorroborated:
        signal = signal_from(entry["report"], entry["basis"], corroborated=False)
        if signal is not None:
            signals.append(signal)
            signal_candidate_ids.append(entry["report"].candidate_id)

    # Everything triage finished with, whether or not it produced a signal. A
    # report that could not be placed or was a repeat of an origin already seen
    # is done; leaving it pending would re-read it every tick forever.
    completed: set[int] = set(signal_candidate_ids)
    observation_to_candidates: dict[int, set[int]] = {}
    for candidate in candidates:
        observation_to_candidates.setdefault(
            int(candidate["observation_id"]), set()
        ).add(int(candidate["id"]))
    for item in (*unplaceable, *outcome.skipped):
        completed.update(
            observation_to_candidates.get(int(item["observation_id"]), set())
            & pending_ids
        )
    completed.update(
        entry["report"].candidate_id
        for entry in outcome.closed
        if entry["report"].candidate_id in pending_ids
    )

    coordinated = None
    if signals:
        if coordinate is None:
            from ecoguard.coordinator.agent import run as coordinate
        coordinated = coordinate(signals)

    # Marked after the coordinator has taken the signals, so a coordinator
    # failure leaves the candidates pending and the next tick retries them
    # rather than losing the reports silently.
    mark_candidates_triaged(completed, at=now)

    logger.info(
        "text triage: %s corroborated, %s uncorroborated, %s unplaceable",
        len(outcome.events), len(outcome.uncorroborated), len(unplaceable),
    )
    return {
        "events": len(outcome.events),
        "uncorroborated": len(outcome.uncorroborated),
        "closed": len(outcome.closed),
        "unplaceable": unplaceable,
        "skipped": outcome.skipped,
        "coordination": coordinated,
    }
