"""Start, stop and inspect a controlled scenario run.

Distinct from /api/demo, which serves pre-baked SharedEvents from a separate
database for screenshots. This runs the *real* pipeline — the same detectors,
coordinator, analysers and planners — over authored evidence, so the output can
be graded against what the evidence was built to mean.

Consumed by: the dashboard's "Run Demo A" control.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ecoguard.demo import sandbox

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scenario")

# Only scenarios listed here can be started, so the endpoint cannot be used to
# point the pipeline at an arbitrary schema.
SCENARIOS = {"demo_a": "ecoguard.demo.scenarios.demo_a"}


def _seeder(scenario: str):
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
