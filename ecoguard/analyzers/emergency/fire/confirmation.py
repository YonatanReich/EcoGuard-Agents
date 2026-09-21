"""Is this a fire at all, or is the satellite looking at something else?

The analyser used to assume the answer was yes. An incident arrived, it was
called a fire, and everything downstream — the ellipse, the exposed
settlements, the evacuation list — was built on an assumption nobody had
tested. That is the wrong way round: a confident evacuation list for a hot
factory roof is worse than no list at all, because somebody acts on it.

The detector already suppresses cells that light routinely, and the coordinator
already merges signals that agree. Neither of those is a judgement about *this*
incident, and neither travels with it. This makes that judgement explicitly,
from evidence the incident is already carrying, and states it so an operator
sees how strong the claim is before reading what follows from it.

The evidence, and why each piece counts
---------------------------------------
**Independent instruments.** Two satellites on separate overpasses seeing the
same cell is a different claim from one satellite seeing it twice. Glint, a hot
roof and a cloud edge do not usually survive a different look angle at a
different hour.

**Instrument confidence.** The product's own flag, already normalised across
the three scales FIRMS reports on.

**Radiative power.** A 90 MW return is not a roof. Small returns are where the
ambiguity lives, so power raises confidence and never lowers it — a genuine
small fire is still a fire.

**Growth across overpasses.** 4.7 to 18.6 to 71.6 MW is a fire taking hold.
A flat trace at the same power for hours is a machine.

**How often this cell lights anyway.** From `firms_baselines` via the signal's
rarity. A cell that has never lit in a year is the strongest evidence here.

**What has burned here before.** Distinct from the rate: `fire_history`
separates a fire-prone area, which burns in seasons, from a standing thermal
source, which burns on a schedule. A cell with a long record of regular
detection is industry however rare any single one looks.

Why this is a judgement and not a probability
---------------------------------------------
Because there is nothing to calibrate a probability against. The only labels
available are settlement-month aggregates that cannot identify an individual
candidate, so any number would be a confidence dressed as a frequency. The
verdict is therefore a band with its reasons attached, and the reasons are
what an operator argues with.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

CONFIRMED = "confirmed"
PROBABLE = "probable"
POSSIBLE = "possible"
DOUBTFUL = "doubtful"

# Distinct from DOUBTFUL, and the distinction is load-bearing. `doubtful` is a
# judgement made against evidence: it was weighed and it does not support a
# fire. `unassessed` is the absence of evidence to weigh — a synthetic case, a
# replay whose signals were not carried, a detector that did not attach any.
#
# Collapsing the two would make an incident with no satellite evidence look
# exactly like one the satellite argues against, and would then penalise it
# downstream. That is the error this module's own docstring warns about, and
# it is easy to make: the first version of this file made it.
UNASSESSED = "unassessed"

# The bands, as scores out of 100. Deliberately coarse: the evidence does not
# support finer, and four bands is what a duty officer can act on differently.
BANDS = ((75, CONFIRMED), (50, PROBABLE), (25, POSSIBLE), (0, DOUBTFUL))

# What each piece of evidence is worth. Written out rather than fitted, for
# the reason in the module docstring, and so a reader who disagrees can point
# at the line they disagree with.
MULTIPLE_SATELLITES = 25      # independent instruments agreeing
STRONG_INSTRUMENT = 15        # the product's own confidence is high
MANY_PIXELS = 15              # a fire lights its neighbours; a roof does not
HIGH_POWER = 20               # too much energy to be a warm surface
GROWING = 15                  # intensity rising across overpasses
RARE_CELL = 20                # this cell does not light up
REPEAT_SIGNALS = 10           # the incident has been seen more than once

PERSISTENT_CELL = -35         # a standing thermal source, whatever else is true
FLAT_TRACE = -15              # same power, hour after hour
SINGLE_WEAK_PIXEL = -15       # one low-confidence pixel and nothing else

# Thresholds for the terms above, in the units the evidence arrives in.
STRONG_CONFIDENCE = 0.75
HIGH_POWER_MW = 25.0
MANY_PIXEL_COUNT = 3
RARE_SHARE = 0.01             # lit on under 1% of observed days
GROWTH_RATIO = 1.5            # newest over oldest across the recent curve
FLAT_RATIO = 1.15


def _signals(incident: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        signal for signal in incident.get("signals") or ()
        if isinstance(signal, Mapping) and signal.get("hazard") == "fire"
    ]


def _growth(detections: Sequence[Mapping[str, Any]]) -> float | None:
    """Newest peak power over oldest, across the recent overpass curve."""
    powers = [
        float(item["peak_frp_mw"])
        for item in detections
        if isinstance(item, Mapping) and item.get("peak_frp_mw") is not None
    ]
    if len(powers) < 2 or powers[0] <= 0:
        return None
    return powers[-1] / powers[0]


def assess(
    incident: Mapping[str, Any],
    *,
    history: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Whether this incident is really a fire, with the reasons either way.

    Args:
        incident: a coordinator incident, whose `signals` carry the satellite
            evidence the detector attached.
        history: an optional `fire_history.persistence` result for the cell.
            Passed in rather than fetched so the judgement stays testable
            without a database, the same split the rest of this package uses.

    Returns:
        dict with `verdict`, a 0-100 `score`, and `reasons` — each an
        explicit `(factor, points, detail)` so the verdict can be argued with
        rather than only believed.

        A verdict is never None. An incident carrying no evidence is
        `unassessed` with a `score` of None — a statement that the question
        was not answered, which downstream must not read as an answer of no.
    """
    signals = _signals(incident)
    reasons: list[dict[str, Any]] = []
    score = 40  # a detection exists at all; the evidence moves it from here

    def note(factor: str, points: int, detail: str) -> None:
        nonlocal score
        score += points
        reasons.append({"factor": factor, "points": points, "detail": detail})

    if not signals:
        return {
            "verdict": UNASSESSED,
            "score": None,
            "reasons": [{
                "factor": "no_fire_signal_on_the_incident",
                "points": 0,
                "detail": "no satellite evidence was carried with this "
                          "incident, so whether it is a fire has not been "
                          "assessed. This is an absence of evidence and not "
                          "evidence of absence.",
            }],
        }

    strongest = max(signals, key=lambda item: float(item.get("value") or 0.0))
    evidence = strongest.get("evidence") or {}

    satellites = list(evidence.get("satellites") or ())
    if len(satellites) > 1:
        note("independent_instruments", MULTIPLE_SATELLITES,
             f"{len(satellites)} products agree: {', '.join(satellites)}")

    confidence = strongest.get("confidence")
    if confidence is not None and float(confidence) >= STRONG_CONFIDENCE:
        note("instrument_confidence", STRONG_INSTRUMENT,
             f"instrument confidence {float(confidence):.2f}")

    pixels = evidence.get("hotspot_count")
    if pixels and int(pixels) >= MANY_PIXEL_COUNT:
        note("multiple_pixels", MANY_PIXELS, f"{pixels} pixels alight")

    power = float(strongest.get("value") or 0.0)
    if power >= HIGH_POWER_MW:
        note("radiative_power", HIGH_POWER, f"{power:.1f} MW")

    curve = evidence.get("recent_detections") or ()
    ratio = _growth(curve)
    if ratio is not None and ratio >= GROWTH_RATIO:
        note("intensity_growing", GROWING,
             f"peak power rose {ratio:.1f}x across {len(curve)} overpasses")
    elif ratio is not None and ratio <= FLAT_RATIO and len(curve) >= 4:
        note("flat_output", FLAT_TRACE,
             f"power steady across {len(curve)} overpasses, which is how a "
             "machine burns and not how a fire does")

    share = evidence.get("detection_share")
    if share is not None and float(share) <= RARE_SHARE:
        note("rare_for_this_cell", RARE_CELL,
             f"this cell lit on {float(share) * 100:.2f}% of observed days")

    if int(incident.get("signal_count") or 0) > 1:
        note("seen_more_than_once", REPEAT_SIGNALS,
             f"{incident['signal_count']} signals attached to this incident")

    if len(satellites) <= 1 and (not pixels or int(pixels) < 2) and (
        confidence is not None and float(confidence) < 0.6
    ):
        note("single_weak_pixel", SINGLE_WEAK_PIXEL,
             "one low-confidence pixel from one product, with nothing "
             "corroborating it")

    if history and history.get("persistent"):
        note("standing_thermal_source", PERSISTENT_CELL,
             f"this cell has lit on {history.get('distinct_days')} of "
             f"{history.get('span_days')} days — the record of an installation "
             "rather than of a fire")

    score = max(0, min(100, score))
    verdict = next(name for threshold, name in BANDS if score >= threshold)
    return {"verdict": verdict, "score": score, "reasons": reasons}


def statement(assessment: Mapping[str, Any]) -> str:
    """The verdict as a sentence, with what carried it."""
    verdict, score = assessment["verdict"], assessment["score"]
    if verdict == UNASSESSED:
        return (
            "Whether this is a fire has not been assessed: no satellite "
            "evidence was carried with the incident. What follows describes "
            "how fire would behave here, not that fire is here."
        )

    opening = {
        CONFIRMED: "This is a fire.",
        PROBABLE: "This is probably a fire.",
        POSSIBLE: "This may be a fire; the evidence is thin.",
        DOUBTFUL: (
            "The evidence does not support calling this a fire. Treat what "
            "follows as conditional."
        ),
    }[verdict]

    supporting = [item for item in assessment["reasons"] if item["points"] > 0]
    against = [item for item in assessment["reasons"] if item["points"] < 0]

    parts = [f"{opening} Detection confidence {score} of 100."]
    if supporting:
        parts.append(
            "For: " + "; ".join(item["detail"] for item in supporting) + "."
        )
    if against:
        parts.append(
            "Against: " + "; ".join(item["detail"] for item in against) + "."
        )
    return " ".join(parts)
