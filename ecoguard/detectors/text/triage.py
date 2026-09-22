"""Candidates in, events and weak events out.

The whole of §4 lives here, and it is two rules:

**An official report is an event.** Authority and media both. No corroboration,
because waiting for a second source to agree with the police is how a system
learns about a fire from the news.

**An unofficial report is a weak event until something agrees with it.** It
goes on the map looking different, it never reaches the allocator, and it
expires quietly if nothing corroborates it.

Three things can corroborate, and the third is the interesting one:

  official      any authority or media report of the same hazard nearby
  independence  two or more distinct origins, after forwards are collapsed
  structured    an open incident of the same hazard nearby

"Structured evidence" needs no new code because the structured detectors
already produce exactly that. A FIRMS hotspot becomes a fire incident; a gauge
exceedance becomes a flood incident; the GSI feed becomes an earthquake
incident. So "is there instrument evidence near this rumour" is "is there an
open incident of this hazard near this rumour", asked of the store that already
holds the answer.

Why forward-dedup is not optional
---------------------------------
Ten operational channels forwarding one message is one person's claim ten
times. Without collapsing them, the unofficial tier corroborates itself on the
second repost and every rumour on Telegram becomes an event within a minute.
Telegram gives us the original channel and post id on a forward, which is an
exact answer; for a message retyped rather than forwarded, near-identical text
is the fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from ecoguard.shared.grid import (
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
)

logger = logging.getLogger(__name__)

# §4's window, both halves configurable because neither is knowable in advance.
CORROBORATION_RADIUS_KM = 2.0
CORROBORATION_WINDOW = timedelta(hours=2)

# How long an uncorroborated report stays on the map. Long enough that a
# satellite overpass or an official statement has a chance to arrive, short
# enough that the map is not a list of yesterday's rumours.
WEAK_EVENT_TTL = timedelta(hours=3)

# Two distinct origins promote. Not three: on a fast-moving fire the second
# independent report is the strongest signal available before the satellite,
# and the origin key already makes "distinct" mean distinct.
INDEPENDENT_REPORTS_REQUIRED = 2

# Above this, two messages are the same claim retyped. Deliberately high —
# two genuinely independent reports of one fire share the town name and little
# else, and collapsing those would be worse than missing a copy-paste.
NEAR_DUPLICATE_RATIO = 0.85

OFFICIAL_TIERS = frozenset({"authority", "media"})


@dataclass(frozen=True)
class Report:
    """One classified message, with everything triage needs and nothing else."""

    candidate_id: int
    observation_id: int
    source_id: str
    tier: str
    hazard: str
    observed_at: datetime
    text: str
    origin_key: str
    latitude: float | None = None
    longitude: float | None = None
    precision_m: float | None = None
    location_text: str | None = None
    update_type: str = "new"
    claim: str | None = None

    @property
    def official(self) -> bool:
        return self.tier in OFFICIAL_TIERS


@dataclass
class TriageOutcome:
    """What one triage run did, without querying to find out."""

    events: list[dict[str, Any]] = field(default_factory=list)
    weak_events: list[dict[str, Any]] = field(default_factory=list)
    promoted: list[dict[str, Any]] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)
    closed: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)


def origin_key(payload: Mapping[str, Any]) -> str:
    """Who originally said this, not who repeated it.

    A forwarded message carries the channel and post it came from, so ten
    reposts of one claim collapse to one key. Anything else is keyed by the
    message itself.
    """
    forwarded = payload.get("forwarded_provenance") or {}
    origin_peer = forwarded.get("origin_peer_id")
    origin_post = forwarded.get("origin_message_id")
    if origin_peer is not None and origin_post is not None:
        return f"forward:{origin_peer}:{origin_post}"

    peer = payload.get("peer_id")
    message_id = payload.get("message_id")
    if peer is not None and message_id is not None:
        return f"message:{peer}:{message_id}"

    # RSS, or a Telegram payload missing its ids: the source plus the item.
    return f"source:{payload.get('source_id')}:{payload.get('item_guid') or ''}"


def near_duplicate(first: str, second: str, *, ratio: float = NEAR_DUPLICATE_RATIO) -> bool:
    """Whether two messages are the same claim rather than two claims.

    For the copy-paste that is not a Telegram forward — a channel retyping
    another channel's post, which carries no provenance at all.
    """
    if not first or not second:
        return False
    return SequenceMatcher(None, first.strip(), second.strip()).ratio() >= ratio


def distinct_origins(reports: Sequence[Report]) -> int:
    """How many genuinely separate sources are behind these reports."""
    keys: list[str] = []
    texts: list[str] = []
    for report in reports:
        if report.origin_key in keys:
            continue
        if any(near_duplicate(report.text, seen) for seen in texts):
            continue
        keys.append(report.origin_key)
        texts.append(report.text)
    return len(keys)


def distance_km(
    first_latitude: float, first_longitude: float,
    second_latitude: float, second_longitude: float,
) -> float:
    """Ground distance, good enough at Israel's scale."""
    import math

    scale = math.cos(math.radians((first_latitude + second_latitude) / 2))
    return math.hypot(
        (second_latitude - first_latitude) * LATITUDE_KM_PER_DEGREE,
        (second_longitude - first_longitude) * LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * scale,
    )


def within_window(
    report: Report,
    other_latitude: float | None,
    other_longitude: float | None,
    other_time: datetime,
    other_precision_m: float | None = None,
    *,
    radius_km: float = CORROBORATION_RADIUS_KM,
    window: timedelta = CORROBORATION_WINDOW,
) -> bool:
    """§4's window: the looser of the two location uncertainties, plus a margin.

    A report located to a town outline and one located to a street corner are
    both talking about the same fire, and demanding they agree to two hundred
    metres would keep them apart. The uncertainty is part of the claim, so the
    radius grows with it rather than being a constant somebody tunes.
    """
    if abs(report.observed_at - other_time) > window:
        return False
    if report.latitude is None or other_latitude is None:
        # No position on one side. Time alone is not enough to say two reports
        # describe one event, and guessing here would merge a Haifa fire with
        # an Eilat one.
        return False

    uncertainty_km = max(
        (report.precision_m or 0.0), (other_precision_m or 0.0)
    ) / 1000.0
    reach = radius_km + uncertainty_km
    return distance_km(
        report.latitude, report.longitude, other_latitude, other_longitude
    ) <= reach


def corroboration_for(
    report: Report,
    *,
    supporting: Sequence[Report],
    open_incidents: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Whether anything agrees with this unofficial report, and what.

    Returns the reason rather than a boolean, because the reason is what the
    operator's card shows and what makes a promotion arguable afterwards.
    """
    nearby = [
        other for other in supporting
        if other.hazard == report.hazard
        and other.observation_id != report.observation_id
        and within_window(
            report, other.latitude, other.longitude,
            other.observed_at, other.precision_m,
        )
    ]

    official = next((other for other in nearby if other.official), None)
    if official is not None:
        return {
            "kind": "official_report",
            "detail": f"{official.tier} source reported the same hazard nearby",
            "source_id": official.source_id,
        }

    for incident in open_incidents:
        if report.hazard not in set(incident.get("hazards") or ()):
            continue
        if within_window(
            report,
            incident.get("latitude"), incident.get("longitude"),
            incident.get("last_signal_at"), incident.get("precision_m"),
        ):
            return {
                "kind": "structured_evidence",
                "detail": (
                    f"open {report.hazard} incident {incident.get('id')} from "
                    "instrument data nearby"
                ),
                "incident_id": incident.get("id"),
            }

    origins = distinct_origins([report, *nearby])
    if origins >= INDEPENDENT_REPORTS_REQUIRED:
        return {
            "kind": "independent_reports",
            "detail": f"{origins} distinct origins reporting the same hazard nearby",
            "origins": origins,
        }
    return None


def triage(
    reports: Sequence[Report],
    *,
    supporting_reports: Sequence[Report] | None = None,
    open_incidents: Sequence[Mapping[str, Any]] = (),
    open_weak_events: Sequence[Mapping[str, Any]] = (),
    at: datetime | None = None,
    ttl: timedelta = WEAK_EVENT_TTL,
) -> TriageOutcome:
    """Sort this tick's reports into events, weak events and promotions.

    Pure: it decides, it does not write. The caller persists the outcome, which
    is what lets all six of §9's Phase 3 scenarios be driven without a database
    or a model.
    """
    now = at or datetime.now(timezone.utc)
    outcome = TriageOutcome()

    # Expiry first, so a report arriving after a long silence is judged against
    # what is still live rather than against a rumour from this morning.
    live_weak = []
    for weak in open_weak_events:
        if weak.get("expires_at") and weak["expires_at"] <= now:
            outcome.expired.append(weak["id"])
        else:
            live_weak.append(weak)

    support = reports if supporting_reports is None else supporting_reports
    for report in sorted(reports, key=lambda item: item.observed_at):
        if report.latitude is None or report.longitude is None:
            # A report with no place is not actionable and never becomes an
            # event. It is kept as a skip with its reason rather than dropped,
            # because "we heard about it and could not place it" is a real
            # state an operator may want to see.
            outcome.skipped.append({
                "observation_id": report.observation_id,
                "reason": "no_resolvable_location",
                "location_text": report.location_text,
            })
            continue

        # A retraction applies to what is already open, whoever sent it — but
        # only an official one closes an event outright.
        if report.update_type == "false_alarm":
            if report.official:
                outcome.closed.append({
                    "hazard": report.hazard,
                    "report": report,
                    "reason": "official_false_alarm",
                })
            else:
                outcome.skipped.append({
                    "observation_id": report.observation_id,
                    "reason": "unofficial_retraction_does_not_close",
                })
            continue

        if report.official:
            outcome.events.append({
                "hazard": report.hazard,
                "report": report,
                "basis": {"kind": "official_source", "tier": report.tier},
            })
            continue

        corroboration = corroboration_for(
            report, supporting=support, open_incidents=open_incidents
        )
        if corroboration is not None:
            outcome.promoted.append({
                "hazard": report.hazard,
                "report": report,
                "basis": corroboration,
            })
            continue

        # Not corroborated. It joins an existing weak event if one is already
        # describing this, and starts one otherwise.
        #
        # Grouping is not tidiness. Ten channels forwarding one message
        # correctly fail to promote — they are one origin — and if each of
        # them also filed its own weak event, the operator would see the same
        # unconfirmed fire ten times on the map. The rule that stops them
        # promoting has to be the rule that stops them multiplying.
        existing = _matching_weak_event(report, live_weak, outcome.weak_events)
        if existing is not None:
            existing["reports"].append(report)
            existing["last_seen_at"] = max(existing["last_seen_at"], report.observed_at)
            continue

        outcome.weak_events.append({
            "hazard": report.hazard,
            "reports": [report],
            "latitude": report.latitude,
            "longitude": report.longitude,
            "precision_m": report.precision_m,
            "location_text": report.location_text,
            "first_seen_at": report.observed_at,
            "last_seen_at": report.observed_at,
            "expires_at": report.observed_at + ttl,
        })

    return outcome


def _matching_weak_event(
    report: Report,
    persisted: Sequence[Mapping[str, Any]],
    pending: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """The weak event this report continues, from this tick or an earlier one.

    A match against a stored row is hydrated into `pending` on the way out, so
    the caller has one list to persist and an update to an existing weak event
    cannot be silently dropped on the floor.
    """
    for candidate in pending:
        if candidate["hazard"] != report.hazard:
            continue
        if within_window(
            report,
            candidate["latitude"], candidate["longitude"],
            candidate["last_seen_at"], candidate["precision_m"],
        ):
            return candidate

    for stored in persisted:
        if stored.get("hazard") != report.hazard:
            continue
        if within_window(
            report,
            stored.get("latitude"), stored.get("longitude"),
            stored.get("last_seen_at"), stored.get("precision_m"),
        ):
            # Same shape as a pending one, carrying the id of the row to
            # update, and added to the pending list so the new report lands
            # somewhere the caller will actually write.
            hydrated = {
                "id": stored.get("id"),
                "hazard": stored.get("hazard"),
                "reports": [],
                "latitude": stored.get("latitude"),
                "longitude": stored.get("longitude"),
                "precision_m": stored.get("precision_m"),
                "location_text": stored.get("location_text"),
                "first_seen_at": stored.get("first_seen_at"),
                "last_seen_at": stored.get("last_seen_at"),
                "expires_at": stored.get("expires_at"),
            }
            pending.append(hydrated)
            return hydrated
    return None
