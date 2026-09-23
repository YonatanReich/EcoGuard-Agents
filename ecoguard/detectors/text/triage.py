"""Candidates in, corroborated and uncorroborated reports out.

Every placeable report leaves here as something the coordinator can act on.
The only question is whether anything else agrees with it:

**Corroborated.** Something independent supports the claim, so it takes the
ordinary path — analyser, then the hazard's planner, then the allocator.

**Uncorroborated.** Nothing supports it yet, so it is passed on *labelled as
such*. It skips the analyser entirely — there is nothing to analyse in a claim
nobody has confirmed, and running a risk model over a rumour produces a number
that looks like evidence — and goes to the advisory planner, which tells the
operator who to phone: the police station responsible for that town and the
local authority. If evidence arrives later it attaches to the same incident and
the incident stops being uncorroborated on its own.

Two things can corroborate, and the second is the interesting one:

  independence  two or more distinct origins, after forwards are collapsed
  structured    an open incident of the same hazard nearby

"Structured evidence" needs no new code because the structured detectors
already produce exactly that. A FIRMS hotspot becomes a fire incident; a gauge
exceedance becomes a flood incident; the GSI feed becomes an earthquake
incident. So "is there instrument evidence near this rumour" is "is there an
open incident of this hazard near this rumour", asked of the store that already
holds the answer.

No source tiers
---------------
There is deliberately no authority/media/unofficial distinction. Judging a
claim by the badge of whoever posted it meant a self-described official channel
was believed outright while the same sentence from anyone else waited three
hours and then expired unseen. Every report is now treated as a claim and
corroboration is the only thing that raises it — so the question the system
answers is "does anything support this", not "do we like the source".

One consequence is deliberate: a retraction no longer closes anything by
itself, because without tiers nothing distinguishes an authoritative "it was a
false alarm" from any other message. Retractions are recorded and left to the
operator.

Why forward-dedup is not optional
---------------------------------
Ten operational channels forwarding one message is one person's claim ten
times. Without collapsing them, reports corroborate themselves on the second
repost and every rumour on Telegram becomes a confirmed event within a minute.
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

from ecoguard.shared.cells import cell_for
from ecoguard.shared.grid import (
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
)

logger = logging.getLogger(__name__)

# §4's window, both halves configurable because neither is knowable in advance.
CORROBORATION_RADIUS_KM = 2.0
CORROBORATION_WINDOW = timedelta(hours=2)

# Retained only so existing callers and migrations that import it keep working.
# Nothing in this module waits any more: a report that is not corroborated on
# the tick it is read is passed on as uncorroborated immediately, and upgrades
# in place if evidence arrives later. The three-hour hold this used to impose
# delayed every genuine report by up to three hours and, because corroboration
# effectively never arrived, ended in silent expiry rather than in anything an
# operator saw.
WEAK_EVENT_TTL = timedelta(hours=3)

# Two distinct origins promote. Not three: on a fast-moving fire the second
# independent report is the strongest signal available before the satellite,
# and the origin key already makes "distinct" mean distinct.
INDEPENDENT_REPORTS_REQUIRED = 2

# Above this, two messages are the same claim retyped. Deliberately high —
# two genuinely independent reports of one fire share the town name and little
# else, and collapsing those would be worse than missing a copy-paste.
NEAR_DUPLICATE_RATIO = 0.85

# Kept for the few readers that still display a source's provenance. Triage
# itself no longer branches on it — see "No source tiers" above.
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


@dataclass
class TriageOutcome:
    """What one triage run did, without querying to find out."""

    # Something independent agrees: the ordinary analyse-then-plan path.
    events: list[dict[str, Any]] = field(default_factory=list)
    # Nothing agrees yet: passed on labelled, straight to the advisory planner.
    uncorroborated: list[dict[str, Any]] = field(default_factory=list)
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


# The variable every text-derived signal carries. A signal with this variable
# is somebody's say-so; anything else came from an instrument.
TEXT_VARIABLE = "report"


def has_instrument_evidence(incident: Mapping[str, Any]) -> bool:
    """Whether anything other than a text report supports this incident.

    An incident with no signals at all is treated as having none, which is the
    fail-closed reading: an incident nobody can show evidence for must not be
    the thing that corroborates the next rumour.
    """
    return any(
        signal.get("variable") != TEXT_VARIABLE
        for signal in incident.get("signals") or ()
        if isinstance(signal, Mapping)
    )


def corroboration_for(
    report: Report,
    *,
    supporting: Sequence[Report],
    open_incidents: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Whether anything agrees with this report, and what.

    Returns the reason rather than a boolean, because the reason is what the
    operator's card shows and what makes the judgement arguable afterwards.

    The `structured_evidence` test deliberately ignores incidents that are
    themselves nothing but text reports. Uncorroborated reports now become
    incidents, so without that filter a rumour would corroborate the next copy
    of itself: report A opens an incident, forward B lands nearby, sees "an open
    incident of this hazard", and is promoted on the strength of A. Forward
    dedup exists precisely to stop that, and reading it back out of the incident
    store would route straight around it. Only instrument evidence — a hotspot,
    a gauge, a seismometer — counts here; a second *independent* claim is the
    `independent_reports` case below, which does collapse forwards.
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

    for incident in open_incidents:
        if report.hazard not in set(incident.get("hazards") or ()):
            continue
        if not has_instrument_evidence(incident):
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
    at: datetime | None = None,
    **_legacy: Any,
) -> TriageOutcome:
    """Sort this tick's reports into corroborated events and uncorroborated ones.

    Pure: it decides, it does not write. The caller persists the outcome and
    hands the signals to the coordinator, which is what lets the whole lane be
    driven without a database or a model.

    Nothing is held back. A report that cannot be corroborated on this pass is
    returned as `uncorroborated` rather than parked, because parking it was
    worth nothing: corroboration effectively never arrived inside the old
    three-hour window, and the report expired without an operator ever seeing
    it. If evidence turns up later it lands on the same incident and the
    incident stops being uncorroborated by itself.

    ``**_legacy`` absorbs the retired ``open_weak_events`` and ``ttl`` keywords
    so an older caller does not crash on the way past; both are ignored.
    """
    now = at or datetime.now(timezone.utc)
    outcome = TriageOutcome()
    support = reports if supporting_reports is None else supporting_reports

    # One advisory per claim, not one per repost. The coordinator would merge
    # co-located signals anyway, but collapsing here keeps the count in the log
    # honest and means a ten-channel forward storm makes one advisory rather
    # than ten identical ones racing to be merged.
    #
    # Deliberately the same two-part test `distinct_origins` uses — the forward
    # key *and* near-duplicate text — because the case that defeats a key-only
    # check is the one that actually happens: a channel that retypes another's
    # post rather than forwarding it has its own origin key and is still the
    # same person's claim.
    seen_origins: list[str] = []
    seen_texts: list[str] = []

    def already_reported(item: Report) -> bool:
        """Whether this claim has already been seen this pass, by origin or wording."""
        if item.origin_key in seen_origins:
            return True
        return any(near_duplicate(item.text, seen) for seen in seen_texts)

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

        # Without source tiers nothing here can tell an authoritative
        # retraction from anyone else typing "false alarm", and auto-closing a
        # live incident on an unverifiable say-so is the one error in this lane
        # that gets someone hurt. Recorded, and left to the operator.
        if report.update_type == "false_alarm":
            outcome.skipped.append({
                "observation_id": report.observation_id,
                "reason": "retraction_recorded_not_acted_on",
                "location_text": report.location_text,
            })
            continue

        corroboration = corroboration_for(
            report, supporting=support, open_incidents=open_incidents
        )
        if corroboration is not None:
            outcome.events.append({
                "hazard": report.hazard,
                "report": report,
                "basis": corroboration,
            })
            continue

        if already_reported(report):
            outcome.skipped.append({
                "observation_id": report.observation_id,
                "reason": "same_claim_already_reported",
                "location_text": report.location_text,
            })
            continue
        seen_origins.append(report.origin_key)
        seen_texts.append(report.text)

        outcome.uncorroborated.append({
            "hazard": report.hazard,
            "report": report,
            "basis": {
                "kind": "uncorroborated_report",
                "detail": (
                    "No independent report and no instrument evidence supports "
                    "this claim yet."
                ),
                "cell_id": cell_for(report.latitude, report.longitude),
                "observed_at": report.observed_at.isoformat(),
            },
        })

    return outcome
