"""Does this signal belong to something already open?

The question requirement 2 asks: recognise "we have seen this, we are already
handling it", so a fire is not re-reported dozens of times while it rages.

Three tests, and two of them are looser than they first look.

**Same hazard.** A rainfall anomaly does not continue a fire. Cross-hazard
joining is a different relation entirely — causation, not identity — and lives
in `packaging.py`.

**Same or adjacent cell.** Not exact match. A fire on a cell boundary lights
pixels either side, and a satellite fix and a ground report of one fire
routinely land a cell apart. Demanding an exact cell is the classic way a
deduplicator splits one event into two and then reports both.

**Within the corroboration window of the incident's last signal** — not of its
first. That distinction is what makes a three-day wildfire one incident: each
new hotspot lands within hours of the previous one, so the window slides
forward and the incident stays alive as long as it keeps being seen. An
incident that stops being seen falls out of the window and is closed by the
quiet-period sweep, so the same cell next week starts fresh.

When several open incidents match, the closest in time wins. Ties are rare and
the alternative — merging them — would be a decision about identity made by
accident.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Sequence

from ecoguard.shared.cells import are_adjacent
from ecoguard.shared.signals import CORROBORATION_WINDOW, CellSignal

# How long an incident may go unseen before it is no longer the thing a new
# signal is describing. Per hazard, because they move at different speeds: a
# fire that nothing has seen for six hours is out or is somebody else's
# problem, while an air quality episode routinely goes quiet overnight and
# resumes, and calling that two episodes would double-count it.
QUIET_PERIOD: dict[str, timedelta] = {
    "fire": timedelta(hours=6),
    # A khamsin runs for days and dips below threshold every night as the air
    # cools. At the six-hour default that becomes a new incident every morning
    # — the same weather system reported as a fresh event daily.
    "fire_weather": timedelta(hours=24),
    "flood": timedelta(hours=3),
    # An earthquake is instantaneous; what persists is its aftershock
    # sequence, and that is what this period is really about. Aftershock rates
    # decay roughly as 1/t (Omori), so the hours after a mainshock carry most
    # of the sequence and a day later it is sparse. At the six-hour default a
    # quiet evening closes the incident while responders are still deployed,
    # and the next aftershock opens a second incident for the same earthquake.
    #
    # Merging is the right error here, unlike everywhere else in this table: a
    # second shock in the same cell a day later usually is the same sequence,
    # and treating it as one event keeps the response attached to it.
    "earthquake": timedelta(hours=24),
    "air_pollution": timedelta(hours=18),
    "heat": timedelta(hours=24),
}

# For a hazard with no entry above. Deliberately short: over-splitting produces
# visible duplicates that someone notices and reports, while over-merging hides
# a real second event inside the first and nobody ever finds out.
DEFAULT_QUIET_PERIOD = timedelta(hours=6)


def quiet_period_for(hazard: str) -> timedelta:
    """How long this hazard may go unseen before its incident closes."""
    return QUIET_PERIOD.get(hazard, DEFAULT_QUIET_PERIOD)


def matches(
    signal: CellSignal,
    incident: dict[str, Any],
    *,
    window: timedelta = CORROBORATION_WINDOW,
    radius: int = 1,
) -> bool:
    """Whether a signal continues an incident rather than starting one.

    Args:
        signal: the new arrival.
        incident: an open incident row, as `incidents.open_incidents` returns
            it — needs `hazards`, `cells` and `last_signal_at`.
        window: how far from the incident's most recent signal this may sit.
        radius: cell steps that still count as the same place.

    Returns:
        bool. False for a closed incident even if everything else lines up:
        a closed incident is a decision that the thing is over, and reopening
        it silently would undo that decision without recording why.
    """
    if incident.get("status") != "open":
        return False
    if signal.hazard not in set(incident.get("hazards") or ()):
        return False

    last_seen = incident.get("last_signal_at")
    if last_seen is None or abs(signal.observed_at - last_seen) > window:
        return False

    return any(
        are_adjacent(signal.cell_id, cell, radius=radius)
        for cell in incident.get("cells") or ()
    )


def best_match(
    signal: CellSignal,
    incidents: Sequence[dict[str, Any]],
    *,
    window: timedelta = CORROBORATION_WINDOW,
    radius: int = 1,
) -> dict[str, Any] | None:
    """The open incident a signal belongs to, or None to start a new one.

    Closest in time wins when several match. Merging the candidates instead
    would be a decision about identity — "these two incidents are one thing" —
    taken by accident, and that decision belongs to the causal packaging step
    where the reason for it can be recorded.
    """
    candidates = [
        incident for incident in incidents
        if matches(signal, incident, window=window, radius=radius)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda incident: abs(signal.observed_at - incident["last_signal_at"]),
    )


def has_gone_quiet(incident: dict[str, Any], at: datetime) -> bool:
    """Whether an open incident has been unseen long enough to close.

    Uses the incident's own primary hazard to pick the period, so a slow
    advisory and a fast fire are not judged by the same clock.
    """
    last_seen = incident.get("last_signal_at")
    if last_seen is None:
        return True
    return at - last_seen > quiet_period_for(incident.get("primary_hazard", ""))
