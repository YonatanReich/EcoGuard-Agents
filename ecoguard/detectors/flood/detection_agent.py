"""Flood-specific evaluation behind the shared detector worker.

The agent has no database or scheduling responsibilities. It receives the
observation window and static context prepared by the worker, then applies the
deterministic rules from ``rules.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

from ecoguard.detectors.flood.rules import (
    FloodCandidate,
    FloodPolicy,
    FloodResolution,
    evaluate_cell,
    evaluate_resolutions,
)


@dataclass(frozen=True)
class FloodEvaluation:
    """The open and resolved transitions produced for one cell."""

    candidates: list[FloodCandidate]
    resolutions: list[FloodResolution]


class FloodDetectionAgent:
    """Evaluate one risk cell with the configured flood policy."""

    def __init__(self, policy: FloodPolicy | None = None) -> None:
        self.policy = policy or FloodPolicy()

    @property
    def lookback(self) -> timedelta:
        """Return the history window the worker must load for each new row."""
        return self.policy.lookback

    def evaluate(
        self,
        *,
        cell_id: str,
        observations: list[Mapping[str, Any]],
        context: Mapping[str, Any] | None,
        baselines: Mapping[tuple[int, int], Mapping[str, Any]],
        active_events: Sequence[Mapping[str, Any]] = (),
    ) -> FloodEvaluation:
        """Return lifecycle transitions for one cell without side effects."""
        active_event_keys = {str(event["event_key"]) for event in active_events}
        candidates = evaluate_cell(
            cell_id,
            observations,
            context,
            baselines,
            self.policy,
        )
        return FloodEvaluation(
            candidates=[
                candidate
                for candidate in candidates
                if candidate.event_key not in active_event_keys
            ],
            resolutions=evaluate_resolutions(
                observations,
                context,
                active_events,
                self.policy,
            ),
        )
