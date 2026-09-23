"""When a fire has grown enough to need more than it was first given.

Compares the current assessment against the one the existing plan was built
from, and asks for more only on a real increase - not on every new reading.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

SOURCE = "הוראה 201 / 201.02.003 §2.1"
SOURCE_TITLE = "נוהל אירועים ארציים"

# §2.1, as published. The Hebrew is the clause text; the English is this
# module's reading of it, kept beside rather than instead of the original so a
# Hebrew-reading reviewer can check the translation.
CRITERIA: tuple[dict[str, Any], ...] = (
    {"clause": "2.1.1", "he": "שריפה במבנה בן 20 קומות ומעלה",
     "en": "fire in a building of 20 floors or more", "evaluable": False},
    {"clause": "2.1.2", "he": "אירוע במבנה עם ריבוי אוכלוסייה",
     "en": "event in a building with a large population "
           "(central station, mall, clinic)", "evaluable": True},
    {"clause": "2.1.3", "he": "אירוע באמצעי הסעת המונים",
     "en": "event in mass transit (train, aircraft, ship)", "evaluable": False},
    {"clause": "2.1.4", "he": 'אירוע בפיקוד מת"ח',
     "en": "event under regional command", "evaluable": False},
    {"clause": "2.1.5", "he": "השתתפות של 10 צוותים ומעלה",
     "en": "participation of 10 teams or more", "evaluable": False},
    {"clause": "2.1.6", "he": "סכנה ליישוב",
     "en": "danger to a settlement", "evaluable": True},
    {"clause": "2.1.7", "he": 'כבאי לכוד / כבאי נפגע ופונה לביה"ח',
     "en": "trapped or injured firefighter evacuated to hospital",
     "evaluable": False},
    {"clause": "2.1.8", "he": "ריבוי אירועים (מעל 10 אירועים למחוז בו\"ז)",
     "en": "more than 10 simultaneous events in one district", "evaluable": False},
    {"clause": "2.1.9", "he": "2 לכודים ומעלה",
     "en": "two or more trapped persons", "evaluable": False},
)

# What counts as "a large population" for 2.1.2. The clause names examples —
# a central station, a mall, a clinic — rather than a number, so this reads it
# as "a site whose occupants cannot simply walk away", which is the same set
# our infrastructure layer already calls life-safety.
LARGE_POPULATION_KINDS = frozenset({
    "hospital", "clinic", "school", "college", "university",
    "kindergarten", "refugee site", "prison", "healthcare facility",
})


def assess(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Whether this incident meets a national-event criterion, and which.

    Args:
        analysis: a `spread_analyzer` result.

    Returns:
        dict with `is_national`, the `triggered` clauses with the evidence for
        each, and `unevaluable` — the clauses this system cannot see. Every
        entry carries the clause path so the verdict cites §2.1.6 rather than
        asserting itself.
    """
    triggered: list[dict[str, Any]] = []

    exposure: Sequence[Mapping[str, Any]] = analysis.get("exposure") or ()
    burning = [item for item in exposure if item.get("exposure") == "burning"]
    threatened = [item for item in exposure if item.get("exposure") == "likely"]

    # 2.1.6 — danger to a settlement. The clause the analyser exists to answer.
    if burning or threatened:
        places = burning or threatened
        triggered.append({
            "clause": "2.1.6",
            "he": "סכנה ליישוב",
            "en": "danger to a settlement",
            "evidence": (
                "fire is inside " if burning else "fire is forecast to reach "
            ) + ", ".join(
                str(item.get("name")) for item in places[:4]
            ),
        })

    # 2.1.2 — a site whose occupants cannot get themselves out.
    sites = [
        site for site in analysis.get("infrastructure_at_risk") or ()
        if site.get("kind") in LARGE_POPULATION_KINDS
        and site.get("exposure") == "likely"
    ]
    if sites:
        triggered.append({
            "clause": "2.1.2",
            "he": "אירוע במבנה עם ריבוי אוכלוסייה",
            "en": "event at a site with a large or non-ambulatory population",
            "evidence": ", ".join(
                f"{site.get('name')} ({site.get('kind')})" for site in sites[:4]
            ),
        })

    unevaluable = [
        {k: item[k] for k in ("clause", "he", "en")}
        for item in CRITERIA if not item["evaluable"]
    ]

    return {
        "is_national": bool(triggered),
        "source": SOURCE,
        "source_title": SOURCE_TITLE,
        "triggered": triggered,
        # Named rather than silently treated as not met. Five of the nine
        # criteria are on-scene facts no satellite can see, and a verdict that
        # hides that invites somebody to stop checking.
        "unevaluable": unevaluable,
        "statement": _statement(triggered, unevaluable),
    }


def _statement(
    triggered: Sequence[Mapping[str, Any]], unevaluable: Sequence[Mapping[str, Any]]
) -> str:
    """The verdict as a sentence an operator can act on or argue with."""
    tail = (
        f" {len(unevaluable)} of the nine criteria in §2.1 cannot be assessed "
        "from remote data — trapped persons, injured firefighters, teams "
        "committed, and simultaneous district load — and must be checked on "
        "scene."
    )
    if not triggered:
        return (
            "No national-event criterion is met by the remotely assessable "
            f"evidence ({SOURCE})." + tail
        )
    clauses = ", ".join(f"§{item['clause']} ({item['en']})" for item in triggered)
    return (
        f"This event meets {SOURCE_TITLE} {SOURCE}: {clauses}. It should be "
        "reported to the national control centre as a national event." + tail
    )
