"""Start, stop and inspect a controlled scenario run.

Distinct from /api/demo, which serves pre-baked SharedEvents from a separate
database for screenshots. This runs the *real* pipeline — the same detectors,
coordinator, analysers and planners — over authored evidence, so the output can
be graded against what the evidence was built to mean.

Consumed by: the Demo scenarios page, which explains how the evidence was
built before it offers to run it, and the dashboard's End-demo control.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ecoguard.demo import sandbox

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scenario")

# Only scenarios listed here can be started, so the endpoint cannot be used to
# point the pipeline at an arbitrary schema.
SCENARIOS = {
    "historical_fires": "ecoguard.demo.scenarios.historical_fires",
    "air_pollution_2026_02_16": "ecoguard.demo.scenarios.air_pollution_2026_02_16",
    "flood_demo": "ecoguard.demo.scenarios.flood_demo",
    "demo_a": "ecoguard.demo.scenarios.demo_a",
    "demo_b": "ecoguard.demo.scenarios.demo_b",
}


# What each scenario is for, in the words the demo page shows before anyone
# presses anything. Kept here rather than in the frontend so the description and
# the thing described cannot drift apart. The catalogue serves them in the
# order of SCENARIOS above.
#
#   incident   what happened, as it happened
#   outcome    what it cost in reality, where that is on record
#   detection  how the system finds it and, for fires, how it forecasts spread
#   value      what that adds over the way it is handled today
#   passes     what the grader requires before it counts the run as a pass
SCENARIO_STORIES: dict[str, dict] = {
    "historical_fires": {
        "label": "Carmel & Jerusalem fires",
        "kicker": "Wildfire · real events",
        "blurb": (
            "Israel's deadliest wildfire and its most recent major one, replayed "
            "from the satellite pixels, weather and news of the day."
        ),
        "incident": [
            "Carmel, 2 December 2010. After an unusually dry autumn, a fire "
            "broke out at about 11:00 on the edge of Isfiya. A dry east wind "
            "drove it west across the Carmel ridge within hours - towards Damon "
            "prison, Beit Oren and Ein Hod.",
            "A Prison Service bus sent to evacuate Damon prison was caught by "
            "the flames on the road below Beit Oren. Most of those on board "
            "were killed.",
            "Jerusalem hills, 30 April 2025, the eve of Independence Day. A "
            "fire started at about 09:30 in Eshtaol Forest by Mesilat Zion, in "
            "a sharav: 11% humidity and an east wind of 30-35 km/h. It reached "
            "Route 1, where drivers abandoned their cars, and ran west-north-"
            "west towards the Latrun villages.",
        ],
        "outcome": [
            "Carmel: 44 people killed - Prison Service cadets, police officers "
            "and a 16-year-old volunteer firefighter. About 32,000 dunam of "
            "forest burned, 81 homes destroyed and 173 damaged, and some "
            "17,000 people evacuated. It took 77 hours and aircraft from "
            "abroad to contain, and it led to the creation of the national "
            "Fire and Rescue Authority.",
            "Jerusalem hills: no one killed; 17 firefighters hurt and more "
            "than a dozen people treated. About 20,000 dunam burned, including "
            "roughly 70% of Canada Park. Neve Shalom, Latrun, Nahshon, Beko'a "
            "and Ta'oz were evacuated, Route 1 was closed, and the fire took "
            "about 30 hours to bring under control.",
        ],
        "detection": [
            "Satellite hot spots open the incident and news reports join it. "
            "A fire-behaviour model forecasts the spread three hours ahead "
            "from that hour's wind and humidity, and every town in its path is "
            "ranked: evacuate now, prepare, or stand by.",
        ],
        "value": [
            "Jerusalem: an alert 37 minutes after ignition, before the first "
            "news report, naming Ta'oz and Neve Shalom to evacuate and Nahshon "
            "and Beko'a to prepare - the villages that were evacuated.",
            "Carmel: the first news report opens the incident before any "
            "satellite pass, and the satellite confirms it rather than "
            "opening a second one.",
            "One card gives the commander the fire district, the local "
            "authority, their phone numbers and the evacuation list.",
        ],
        "passes": (
            "Each fire passes only if it is detected, placed on the burning "
            "area, joined by the right news report, and its plan names the "
            "right fire district and authority, warns the towns the fire "
            "reached and evacuates the ones that were evacuated."
        ),
    },
    "air_pollution_2026_02_16": {
        "label": "Dust storm, 16 Feb 2026",
        "kicker": "Air pollution · real event",
        "blurb": (
            "The dust storm that covered the whole country on 16 February 2026, "
            "replayed from the Ministry's own station readings."
        ),
        "incident": [
            "On 16 February 2026 south-easterly winds carried dust from Jordan "
            "across Israel. By late morning particle levels were high at "
            "stations from the Galilee to Eilat.",
            "At 11:32 the Ministries of Environmental Protection and Health "
            "issued a warning of high to very high air pollution in all parts "
            "of the country, expected to last until Wednesday 18 February.",
        ],
        "outcome": [
            "The advice to the public: people in vulnerable groups should "
            "avoid strenuous outdoor activity, and everyone else should "
            "reduce it.",
            "On the Ministry's air-quality scale the readings sat at low to "
            "very low quality nationwide - in Eilat around -384, near the "
            "bottom of the scale, and in Arad around -182.",
        ],
        "detection": [
            "One or two Ministry stations stand for each of its 13 regions. A "
            "region is flagged when its readings rise well above what is "
            "normal there for the month and hour, and the advice comes word "
            "for word from the Ministry's own guidance.",
        ],
        "value": [
            "The same alarm the Ministry raised, in all 13 regions, at 11:30 - "
            "from raw readings alone.",
            "One card per region rather than one national notice, so each "
            "area sees its own reading and its own advice.",
        ],
        "passes": (
            "Each of the 13 regions passes only if it is detected, placed at "
            "its station, rated low or very low on the Ministry scale, and "
            "given the Ministry's advice."
        ),
    },
    "flood_demo": {
        "label": "Hadera & Zeelim floods",
        "kicker": "Flood · real events",
        "blurb": (
            "A river that flooded a city and a desert wadi that flooded a road, "
            "replayed from the stream gauges' own readings."
        ),
        "incident": [
            "Nahal Hadera, 8 January 2013. A severe winter storm sent the "
            "stream to the highest peak flow it had ever recorded. It burst "
            "its banks and flooded neighbourhoods of Hadera.",
            "Nahal Zeelim, 1 November 2023. The season's first flash flood ran "
            "down the dry wadi in the Judean Desert; the first wave reached "
            "the road at 16:52 and a second at 17:03.",
        ],
        "outcome": [
            "Hadera: firefighters rescued dozens of residents from Tzahal "
            "Street by rubber boat and from the roof of a fire engine. Homes "
            "on Borochov Street were wrecked, and a flooded power substation "
            "left much of the city without electricity overnight.",
            "Zeelim: the road was closed for hours. Roadside cameras helped "
            "warn drivers of the second wave.",
        ],
        "detection": [
            "Water Authority gauges report flow every few minutes. Two high "
            "readings in a row confirm a flood; what counts as high depends "
            "on whether the stream normally flows or is normally dry.",
        ],
        "value": [
            "Hadera: confirmed at 11:22, with the escalation flagged about 20 "
            "minutes later.",
            "Zeelim: confirmed at 16:35, 17 minutes before the wave reached "
            "the road - time to close the crossing and warn drivers.",
        ],
        "passes": (
            "Each flood passes only if it is detected from the readings, "
            "placed at its gauge, and routed as an emergency."
        ),
    },
    "demo_a": {
        "label": "Demo A: one of each",
        "kicker": "Mixed hazards · constructed",
        "blurb": (
            "One event per hazard, each on its own, with noise around it: does "
            "the system find what is there and leave alone what is not?"
        ),
        "incident": [
            "A large fire in central Eilat, a moderate one in the Carmel, a "
            "flash flood in Nahal Ashalim, a dust episode in the Negev, and a "
            "fire claim in Netanya that nothing else confirms.",
        ],
        "outcome": [],
        "detection": [
            "Constructed events, turned into the raw readings each provider "
            "would have sent.",
        ],
        "value": [
            "Shows each detector on its own, and that a single unconfirmed "
            "claim is shown as unconfirmed rather than as a fire.",
        ],
        "passes": (
            "Each event passes if it is found, placed and routed as authored - "
            "including the Netanya claim, which must stay unverified."
        ),
    },
    "demo_b": {
        "label": "Demo B: overlapping events",
        "kicker": "Mixed hazards · constructed",
        "blurb": (
            "Events that overlap and interfere: can the system tell one event "
            "from two?"
        ),
        "incident": [
            "Two fires burning at once near Jerusalem and Beit Shemesh, an "
            "earthquake with aftershocks and a second quake in Eilat, a rising "
            "flood, a worsening dust episode, and one fire claim forwarded by "
            "three channels from the same origin.",
        ],
        "outcome": [],
        "detection": [
            "Constructed events, turned into the raw readings each provider "
            "would have sent.",
        ],
        "value": [
            "Shows that three forwards of one message count as one source, "
            "aftershocks join their main quake, and neighbouring fires stay "
            "separate.",
        ],
        "passes": (
            "Each event passes if it becomes exactly the incident it was "
            "authored as - no merges, no splits, nothing unaccounted for."
        ),
    },
}


def _ground_truth(scenario: str) -> list[dict]:
    """The events a scenario was built to contain, as authored."""
    from importlib import import_module

    module = import_module(SCENARIOS[scenario])
    return [dict(item) for item in getattr(module, "GROUND_TRUTH", ())]


@router.get("/catalog")
def scenario_catalog():
    """Every scenario and the events it was built to contain.

    Read before a run rather than after, so the page can say what the system is
    about to be asked to find. Grading a run the operator has not been told the
    shape of proves nothing to them.
    """
    catalog = []
    for scenario in SCENARIOS:
        try:
            events = _ground_truth(scenario)
        except Exception:
            logger.exception("could not read the authored events for %s", scenario)
            events = []
        story = SCENARIO_STORIES.get(scenario, {})
        catalog.append(
            {
                "id": scenario,
                "label": story.get("label", scenario.replace("_", " ").title()),
                "blurb": story.get("blurb", ""),
                "story": story,
                "event_count": len(events),
                "events": [
                    {
                        "id": item.get("id"),
                        "event": item.get("event"),
                        "hazard": item.get("hazard"),
                        "latitude": item.get("latitude"),
                        "longitude": item.get("longitude"),
                        "expect_route": item.get("expect_route"),
                        "expect_detected": item.get("expect_detected"),
                        "notes": item.get("expect_notes"),
                    }
                    for item in events
                ],
            }
        )
    return {"scenarios": catalog}


def _seeder(scenario: str):
    """The function that fills the sandbox for one named scenario."""
    from importlib import import_module

    module = import_module(SCENARIOS[scenario])
    return module.seed


@router.get("/status")
def scenario_status():
    """Whether a scenario is running, and what it has produced so far."""
    try:
        return sandbox.status()
    except Exception as error:
        logger.error("scenario status failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Scenario state unavailable.")


@router.post("/start/{scenario}")
def scenario_start(scenario: str):
    """Enter the sandbox, seed it, and pause the collectors.

    The detection wave keeps running, so the first results appear on the next
    tick rather than immediately.
    """
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {scenario!r}.")
    try:
        return sandbox.start(scenario, seeder=_seeder(scenario))
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except Exception as error:
        logger.error("scenario start failed: %s", error, exc_info=True)
        # A half-entered sandbox would leave the live pipeline writing to the
        # wrong schema, so the search path is put back before reporting.
        try:
            sandbox.stop()
        except Exception:
            logger.exception("could not restore the live search path")
        raise HTTPException(status_code=500, detail="Could not start the scenario.")


@router.post("/stop")
def scenario_stop(keep_data: bool = True):
    """Return to the live tables and restart the collectors."""
    try:
        return sandbox.stop(keep_data=keep_data)
    except Exception as error:
        logger.error("scenario stop failed: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not stop the scenario.")


@router.get("/report/{scenario}")
def scenario_report(scenario: str):
    """Grade what the run produced against what the evidence was built to mean."""
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {scenario!r}.")
    try:
        from ecoguard.demo.grade import grade

        story = SCENARIO_STORIES.get(scenario, {})
        return {
            **grade(scenario),
            "label": story.get("label", scenario),
            "passes": story.get("passes", ""),
        }
    except Exception as error:
        logger.error("scenario report failed: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not build the report.")
