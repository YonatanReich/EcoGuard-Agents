"""The dispatch reconstruction, as configuration rather than as code.

WHAT THIS IS NOT
================
This is not the Fire Authority's dispatch procedure. Their real mechanism is a
lookup table — טבלת ההנחיה לשיגור — that lives in שלהבת, their CAD system. It
is not published and we do not have it. Everything below is a reconstruction
derived from thresholds that *are* published, and every plan built on it must
carry `dispatch_table_unavailable` in its coverage gaps.

The distinction matters because a grade and a team count look identical on the
page whether they came from the authority's table or from this file.

WHAT IT IS ANCHORED ON
======================
Two numbers here are cited rather than chosen:

* **Ten teams** is a national-event criterion in נוהל אירועים ארציים
  (הוראה 201 / 201.02.003 §2.1.5). That is why the top grade begins at ten and
  not at some other number.
* **Danger to a settlement** is a criterion in the same clause list (§2.1.6),
  which is why a settlement inside the projected footprint is what lifts an
  event to grade 3 — the grade at which our inter-district procedure permits
  cross-district dispatch.

The band widths between them are interpolation. Grade 4's lower bound of six
is informed by the fire commissioner's statement to the Knesset National
Security Committee that 32% of events required over four hours of fighting by
at least four teams — which places four in the common-significant range rather
than the exceptional one, so the exceptional band starts above it.

These are tunable on purpose. Change them here; do not spread them into the
selection code.
"""

from __future__ import annotations

from typing import Any

# Grade to team count. `trigger` is documentation for the reader; the logic
# that assigns a grade lives in `dispatch.py` and is tested against this table.
GRADES: dict[int, dict[str, Any]] = {
    1: {
        "teams": 1,
        "trigger": "open terrain, no structures in the projected footprint",
        "cross_district": False,
    },
    2: {
        "teams": 3,
        "teams_min": 2,
        "trigger": "structures in the footprint, no settlement threatened",
        "cross_district": False,
    },
    3: {
        "teams": 5,
        "teams_min": 4,
        "trigger": "a settlement lies inside the projected footprint",
        "cross_district": True,
        "basis": "201.02.003 §2.1.6 — danger to a settlement",
    },
    4: {
        "teams": 8,
        "teams_min": 6,
        "trigger": "a settlement plus extreme fire weather, or several "
                   "localities affected",
        "cross_district": True,
    },
    5: {
        "teams": 12,
        "teams_min": 10,
        "trigger": "national-event criteria met",
        "cross_district": True,
        "basis": "201.02.003 §2.1.5 — ten teams or more",
    },
}

# The grade at which a neighbouring district may be drawn on at all. Below it
# the event is the home district's to handle, per the general rule that each
# district contains events in its own sector.
CROSS_DISTRICT_GRADE = 3

# How many initial-response teams may come from outside the district. The
# procedure bounds this at one; it is not a licence to pull from every
# neighbour, and generalising it would turn an exception into a habit.
INITIAL_RESPONSE_TEAMS_FROM_OUTSIDE = 1

# What lifts grade 3 to grade 4. Both are conditions the analyser measures.
EXTREME_FIRE_WEATHER_SEVERITY = 85     # spread severity out of 100
MULTIPLE_LOCALITIES = 2                # settlements inside the footprint

# Teams a single station may contribute.
#
# The rule we want is "its appliances minus one — never strip a station bare".
# We cannot apply it: `fire_stations.tags` carries OSM address and telephone
# metadata and no appliance counts, for 111 of 118 stations. So capacity is
# approximated from the `regional` flag, which distinguishes the 29 regional
# stations from the 89 local ones, and the approximation is declared on every
# plan that rests on it.
#
# The cap is what enforces "never strip a station bare" in the absence of the
# real number: a station contributes at most this and the remainder is sought
# elsewhere.
TEAMS_PER_STATION = {True: 3, False: 2}   # keyed by `regional`

# The two request types, which carry different authority and different
# realistic timelines. Kept apart in the output because conflating them would
# imply that force completion is as immediate as initial response.
IMMEDIATE_DISPATCH = "הנחיה לשיגור"
FORCE_COMPLETION = 'השלמת פק"ל'

REQUEST_TYPES = {
    IMMEDIATE_DISPATCH: {
        "english": "initial response dispatch",
        "approval": "none required",
        "routing": "direct to station",
        "note": "the national control centre is notified for information only",
    },
    FORCE_COMPLETION: {
        "english": "force completion",
        "approval": "national control centre",
        "routing": "via the district control centre",
        "note": "slower; do not plan initial response around it",
    },
}

# Stated on every dispatch result rather than in documentation, because the
# result is what gets forwarded and the documentation is what stays behind.
LIMITS = (
    "dispatch_table_unavailable: the authority's טבלת ההנחיה לשיגור lives in "
    "the שלהבת CAD system and is not available here. Grades and team counts "
    "are a reconstruction from published thresholds, not the authority's "
    "procedure.",
    "station_appliance_counts_unavailable: per-station vehicle counts are not "
    "in the database, so station capacity is approximated from the regional "
    "flag rather than counted.",
)
