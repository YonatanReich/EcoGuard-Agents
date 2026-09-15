"""Which analyser an incident is for: does anyone get dispatched?

The split is about the **response**, not the severity. A heat advisory can
matter enormously and still belongs on the advisory side, because nobody drives
anywhere because of it. A small fire is an emergency however small, because an
engine rolls.

  emergency      needs EMS, police or fire on scene — fire, flood, earthquake
  non_emergency  advisory only — air quality, extreme heat, reservoir levels

A hybrid incident returns **both**, and that is the point rather than an
awkward edge case. A fire with a smoke plume needs a brigade at the fire and a
health warning in the towns downwind: different audiences, different actions,
one event. Collapsing it to the more urgent queue alone turns a public health
warning into a footnote inside a firefighting plan.
"""

from __future__ import annotations

from typing import Iterable

from ecoguard.shared.signals import AIR_QUALITY, FIRE, FLOOD, HEAT

EMERGENCY = "emergency"
NON_EMERGENCY = "non_emergency"

# Hazards that put someone in a vehicle.
EMERGENCY_HAZARDS = frozenset({FIRE, FLOOD, "earthquake"})

# Hazards that produce advice.
ADVISORY_HAZARDS = frozenset({AIR_QUALITY, HEAT, "water_level"})


class UnroutableHazard(ValueError):
    """A hazard nobody has decided the response posture for."""


def queue_for(hazard: str) -> str:
    """The single queue one hazard belongs to.

    Raises rather than defaulting. A new hazard silently landing in the
    advisory queue would mean nobody is dispatched to it, and that failure is
    invisible — the queue would simply be shorter than it should be. Making it
    an error forces the decision to be made by someone who knows the answer.
    """
    if hazard in EMERGENCY_HAZARDS:
        return EMERGENCY
    if hazard in ADVISORY_HAZARDS:
        return NON_EMERGENCY
    raise UnroutableHazard(
        f"{hazard!r} is in neither EMERGENCY_HAZARDS nor ADVISORY_HAZARDS; "
        "add it to one in ecoguard/coordinator/queues.py"
    )


def queues_for(hazards: Iterable[str]) -> tuple[str, ...]:
    """Every queue an incident belongs to, emergency first when both apply.

    Ordered rather than a set so the result is stable to compare and to store.
    Emergency leads because a reader scanning one incident wants the dispatch
    answer before the advisory one.
    """
    queues = {queue_for(hazard) for hazard in hazards}
    if not queues:
        raise UnroutableHazard("an incident with no hazards has no queue")
    return tuple(
        queue for queue in (EMERGENCY, NON_EMERGENCY) if queue in queues
    )


def is_hybrid(hazards: Iterable[str]) -> bool:
    """Whether this incident spans more than one hazard."""
    return len(set(hazards)) > 1
