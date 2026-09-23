"""Earthquake severity on the shared 0-100 operational risk scale.

Mirrors `analyzers/emergency/flood/risk_scale.py`. The point of both is that
the allocator has to rank a fire, a flood and an earthquake competing for the
same stations, and it can only do that if the three produce one comparable
number.

Earthquake carried none until now. It was given `risk_score=None` on purpose,
with the comment that policy-driven requests do not receive a fabricated risk
score, and that instinct was right: inventing a number so earthquakes would
sort somewhere is exactly the failure to avoid. But the alternative it settled
on was a flat "after everything else", which meant an M6.0 queued behind a
brush fire.

What changed is that there is something real to derive a score from. The
impact analyser already counts the population inside the estimated impact area
by PostGIS intersection, and the magnitude is observed. Both are facts, so the
score below is derived rather than invented -- the same standard flood's scale
meets.
"""

from __future__ import annotations

from ecoguard.shared.schemas import risk_level_for_score

# The scale the allocator compares against, shared with Fire and Flood.
RISK_SEMANTICS = "detected_event_operational_risk"

# Below this an earthquake never becomes a dashboard event, so it never
# reaches allocation and has no operational risk to state.
MIN_SCORED_MAGNITUDE = 3.5

# Magnitude sets the base, on Flood's 40/60/80/100 steps so the two land in
# the same places on the shared scale.
BASE_BY_MAGNITUDE: tuple[tuple[float, int], ...] = (
    (4.5, 40),
    (5.5, 60),
    (6.5, 80),
)
MAX_BASE = 100

# Population inside the impact area moves it. This is the whole reason the
# score exists: the same magnitude under a city and under open desert are not
# the same emergency, and ranking them identically sends engines to the wrong
# one.
ADJUSTMENT_BY_POPULATION: tuple[tuple[int, int], ...] = (
    (1, -20),
    (10_000, -10),
    (100_000, 0),
    (500_000, 10),
)
MAX_ADJUSTMENT = 20


def earthquake_operational_risk(
    magnitude: float,
    *,
    population_at_risk: int | None = None,
) -> tuple[int, str]:
    """Return a 0-100 score and the level the shared Fire scale derives.

    Args:
        magnitude: as reported by GSI.
        population_at_risk: people inside the estimated impact area, or None
            when the intersection could not be read. None means the score is
            the magnitude band alone -- a narrower basis, not a guess. A count
            of zero is a counted zero and lowers the score; the two are
            different and must not collapse into each other.

    Raises:
        ValueError: below the dashboard threshold, where no event exists.
    """

    if magnitude < MIN_SCORED_MAGNITUDE:
        raise ValueError("earthquake below the dashboard threshold has no risk")

    base = MAX_BASE
    for ceiling, score in BASE_BY_MAGNITUDE:
        if magnitude < ceiling:
            base = score
            break

    adjustment = 0
    if population_at_risk is not None:
        adjustment = MAX_ADJUSTMENT
        for ceiling, value in ADJUSTMENT_BY_POPULATION:
            if population_at_risk < ceiling:
                adjustment = value
                break

    score = max(0, min(100, base + adjustment))
    level = risk_level_for_score(score)
    if level is None:  # Defensive: every reachable score is in range.
        raise ValueError("earthquake operational risk level is unavailable")
    return score, level


__all__ = [
    "ADJUSTMENT_BY_POPULATION",
    "BASE_BY_MAGNITUDE",
    "MIN_SCORED_MAGNITUDE",
    "RISK_SEMANTICS",
    "earthquake_operational_risk",
]
