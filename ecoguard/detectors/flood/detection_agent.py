"""Flood-specific evaluation behind the shared detector worker.

The agent has no database or scheduling responsibilities. It receives the
hydrometric observation window prepared by the worker, then applies the
deterministic station rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from ecoguard.detectors.flood.station_rules import (
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

    def accepts_pending(self, observation: Mapping[str, Any]) -> bool:
        """Reject delayed backfills and implausible future timestamps."""
        observed_at = observation.get("observed_at")
        ingested_at = observation.get("ingested_at")
        if not isinstance(observed_at, datetime) or not isinstance(
            ingested_at, datetime
        ):
            return False
        if (
            observed_at.tzinfo is None
            or observed_at.utcoffset() is None
            or ingested_at.tzinfo is None
            or ingested_at.utcoffset() is None
        ):
            return False
        lag = ingested_at - observed_at
        return (
            -self.policy.maximum_future_skew
            <= lag
            <= self.policy.maximum_ingestion_lag
        )

    def evaluate(
        self,
        *,
        cell_id: str,
        observations: list[Mapping[str, Any]],
        active_events: Sequence[Mapping[str, Any]] = (),
    ) -> FloodEvaluation:
        """Return lifecycle transitions for one cell without side effects."""
        active_event_keys = {str(event["event_key"]) for event in active_events}
        candidates = evaluate_cell(cell_id, observations, self.policy)
        return FloodEvaluation(
            candidates=[
                candidate
                for candidate in candidates
                if candidate.event_key not in active_event_keys
            ],
            resolutions=evaluate_resolutions(
                observations,
                active_events,
                self.policy,
            ),
        )
