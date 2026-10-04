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
    "demo_a": "ecoguard.demo.scenarios.demo_a",
    "demo_b": "ecoguard.demo.scenarios.demo_b",
    "flood_demo": "ecoguard.demo.scenarios.flood_demo",
    "earthquake_demo": "ecoguard.demo.scenarios.earthquake_demo",
}


# What each scenario is for, in the words the demo page shows before anyone
# presses anything. Kept here rather than in the frontend so the description and
# the thing described cannot drift apart.
SCENARIO_BLURBS = {
    "earthquake_demo": (
        "The 24 August 1984 Jezreel Valley earthquake, replayed from its "
        "official GSI catalogue record. Follow detection, modelled shaking "
        "over land, response planning and station allocation."
    ),
    "demo_a": (
        "One event per hazard, each on its own, with noise around it. The "
        "question it answers is whether the system finds what is there and "
        "leaves alone what is not."
    ),
    "demo_b": (
        "Events that overlap and interfere: two fires at once, an earthquake "
        "with aftershocks, a claim repeated by three channels from one origin. "
        "The question is whether the system can tell one event from two."
    ),
    "flood_demo": (
        "Two historical floods replayed from measured station data: a "
        "perennial stream in Hadera and an ephemeral stream at Zeelim. The "
        "question is whether the detector applies the correct regime-specific "
        "rule early enough to support action."
    ),
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
        catalog.append(
            {
                "id": scenario,
                "label": scenario.replace("_", " ").title(),
                "blurb": SCENARIO_BLURBS.get(scenario, ""),
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

        return grade(scenario)
    except Exception as error:
        logger.error("scenario report failed: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not build the report.")
