"""Turning the thinking half of the system on and off while it runs.

Collection is never affected. This starts and stops detection, coordination,
analysis and planning - the half that costs money per event and that produces
broken incidents when the model key is absent.

A switch rather than a restart, because a restart resets every collector's
timer and the point of pausing is to keep collecting.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ecoguard import pipeline_switch

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class PipelineState(BaseModel):
    """Whether the pipeline is running, and what that covers."""

    enabled: bool
    collectors_running: bool = True
    detail: str


class PipelineRequest(BaseModel):
    """The state to put the pipeline into."""

    enabled: bool


def _state() -> PipelineState:
    """The current state, described in the terms an operator thinks in."""
    enabled = pipeline_switch.is_enabled()
    return PipelineState(
        enabled=enabled,
        detail=(
            "detecting, analysing and planning"
            if enabled
            else "paused - collecting only, no incidents opened and no model calls"
        ),
    )


@router.get("")
def read_pipeline() -> PipelineState:
    """Whether detection and everything after it is running."""
    return _state()


@router.post("")
def write_pipeline(request: PipelineRequest) -> PipelineState:
    """Start or pause detection and everything after it.

    Takes effect on the next wave, within the detection interval. Collectors
    are untouched either way.
    """
    pipeline_switch.set_enabled(request.enabled)
    return _state()
