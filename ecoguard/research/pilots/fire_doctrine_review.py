"""The analyser's output compared against published firefighting doctrine.

This is the substitute for having a fire officer read the reports, and it is a
weaker thing than that. It compares what the analyser produces against doctrine
that can be cited, which catches structural omissions — a decision input the
doctrine names and the analyser does not supply. It cannot catch a number that
is plausible and wrong, and it is not a professional review.

Each finding names the doctrine, quotes the part being tested, states what the
analyser does, and grades it. Sources are recorded so a reader can disagree
with the reading rather than only with the verdict.
"""

from __future__ import annotations

from typing import Any

ALIGNED = "aligned"
PARTIAL = "partial"
GAP = "gap"

SOURCES = {
    "rsg": (
        "Ready, Set, Go! — International Association of Fire Chiefs, "
        "as published by Los Angeles Fire Department",
        "https://lafd.org/ready-set-go",
    ),
    "trigger": (
        "NWCG 6 Minutes for Safety — Proper Use of Trigger Points",
        "https://www.nwcg.gov/6mfs/weather-fire-behavior/proper-use-of-trigger-points",
    ),
    "lces": (
        "NWCG S-131 Unit 3 — Lookouts, Communications, Escape Routes and "
        "Safety Zones (LCES), after Gleason",
        "https://www.nwcg.gov/training/courses/"
        "s-131-unit-3-lookouts-communications-escape-routes-and-safety-zones-lces",
    ),
    "triage": (
        "USFA/NFA — Structure Triage During Wildland/Urban Interface Fires "
        "(Brown), and USFS RMRS modelling of firefighter defensibility "
        "assessments",
        "https://apps.usfa.fema.gov/pdf/efop/tr_94kb.pdf",
    ),
}

FINDINGS: tuple[dict[str, Any], ...] = (
    {
        "doctrine": "rsg",
        "topic": "Evacuation staging has three levels, not two",
        "doctrine_says": (
            "Ready, Set, Go! stages civilian evacuation in three levels: Ready "
            "(be aware and begin preparing), Set (prepare to leave, be ready to "
            "go at a moment's notice), and Go (leave now)."
        ),
        "analyser_does": (
            "Produces exactly three priorities — standby, prepare, immediate — "
            "assigned from exposure class and arrival time, sorted worst-first "
            "then soonest, each carrying the responsible authority's telephone "
            "number."
        ),
        "verdict": ALIGNED,
        "note": (
            "The mapping is one-to-one and was arrived at independently; the "
            "three-level structure is the established civilian staging model."
        ),
    },
    {
        "doctrine": "trigger",
        "topic": "A trigger point prompts reassessment; it does not decide",
        "doctrine_says": (
            "Trigger points are predetermined cues that prompt reevaluation of "
            "the current and potential situation and its associated risks, "
            "rather than serving as decision-makers."
        ),
        "analyser_does": (
            "States in the evacuation constants that the priorities are read "
            "off the forecast rather than out of a protocol, that they are a "
            "statement about the fire rather than a lawful order, and that the "
            "authority to order an evacuation belongs to the response planner "
            "and the incident commander."
        ),
        "verdict": ALIGNED,
        "note": (
            "This is the distinction most easily lost when a system starts "
            "printing the word EVACUATE next to a town name, and it is made "
            "explicitly in the code and on the page."
        ),
    },
    {
        "doctrine": "trigger",
        "topic": "Trigger points must be reevaluated as conditions change",
        "doctrine_says": (
            "Trigger points are set against operational or environmental "
            "limits and are reevaluated through the operational period as the "
            "situation develops."
        ),
        "analyser_does": (
            "Produces a single assessment for a stated horizon, from the "
            "weather of one hour. Nothing re-runs it as the fire develops, and "
            "the report carries no expiry."
        ),
        "verdict": GAP,
        "note": (
            "The limits do say arrival times assume the forecast wind holds "
            "for the whole horizon, which is honest about the assumption but "
            "does not schedule the reassessment doctrine requires. A report "
            "three hours old reads exactly like one three minutes old."
        ),
    },
    {
        "doctrine": "lces",
        "topic": "LCES — escape routes and safety zones",
        "doctrine_says": (
            "Lookouts, Communications, Escape Routes and Safety Zones must be "
            "identified before they are needed and reevaluated through the "
            "operational period. A minimum of two escape routes from the work "
            "location to a safety zone is required whenever firefighters work "
            "near an objective hazard."
        ),
        "analyser_does": (
            "Supplies the fire's heading, rate and forecast extent, which bear "
            "on where a crew must not be. It supplies no escape routes and no "
            "safety zones, and its own limits state that barriers finer than "
            "the land-cover grid — a road, a firebreak, a wadi — are invisible "
            "to it."
        ),
        "verdict": GAP,
        "note": (
            "This is the sharpest omission found. The analyser supports the "
            "civil side of the incident — who is exposed, who should move — "
            "and does not support the firefighter-safety side at all. Road "
            "geometry exists in OpenStreetMap and is already used elsewhere in "
            "this repository for routing; it is not read here."
        ),
    },
    {
        "doctrine": "triage",
        "topic": "The inputs that decide whether a structure is defensible",
        "doctrine_says": (
            "Structures are classified not threatened, threatened but "
            "defensible, or threatened and non-defensible. Modelling of "
            "firefighters' own assessments found the presence of a safety zone "
            "the most important factor, with road proximity, vegetation "
            "composition and topography also of high importance."
        ),
        "analyser_does": (
            "Supplies vegetation composition (nine cover fractions) and "
            "topography (mean slope, steepest slope, aspect) for the ground "
            "the fire is on. It supplies neither safety-zone presence nor road "
            "proximity."
        ),
        "verdict": PARTIAL,
        "note": (
            "Two of the four named factors, and the two it lacks include the "
            "one the study ranked most important. The analyser is a useful "
            "input to structure triage and cannot perform it."
        ),
    },
    {
        "doctrine": "triage",
        "topic": "The wildland/urban interface must be visible as such",
        "doctrine_says": (
            "Structure triage applies where fire behaviour, construction and "
            "adjacent fuels meet — the interface — which has to be recognised "
            "before the tactic is chosen."
        ),
        "analyser_does": (
            "States the built-up share of the ground whenever it reaches a "
            "third, and says explicitly that the spread forecast covers "
            "wildland fuel only and that fire in the structures themselves "
            "behaves differently and is not modelled."
        ),
        "verdict": ALIGNED,
        "note": (
            "Added after the Petah Tikva scenario reported a wildland run "
            "through a city without qualification. The threshold is the "
            "interface the triage doctrine is written about."
        ),
    },
    {
        "doctrine": "lces",
        "topic": "Suppression is not modelled, and the output says so",
        "doctrine_says": (
            "Doctrine assumes a fire under active suppression with crews, "
            "engines and aircraft committed against it."
        ),
        "analyser_does": (
            "Models unopposed spread and states on every result that no crew, "
            "engine, aircraft or existing containment is included."
        ),
        "verdict": ALIGNED,
        "note": (
            "Corroborated by the historical replay: the forecast head ran "
            "about a third further than the fire actually did over three "
            "hours, which is the direction and rough magnitude an unsuppressed "
            "model should over-predict a fire that was being fought."
        ),
    },
)


def summary() -> dict[str, int]:
    counts = {ALIGNED: 0, PARTIAL: 0, GAP: 0}
    for finding in FINDINGS:
        counts[finding["verdict"]] += 1
    return counts
