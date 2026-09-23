"""How many units of each type a fire of a given severity needs.

A fixed table rather than a judgement, so the same fire always produces the
same requirement and a reviewer can check it against doctrine.
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
