"""Pure flood-domain evaluation behind persisted observation processing."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from ecoguard.detectors.flood.station_rules import FloodPolicy, evaluate_cell
from ecoguard.shared.signals import CellSignal


class FloodDetectionAgent:
    """Evaluate hydrometric readings without database or scheduler concerns."""

    def __init__(self, policy: FloodPolicy | None = None) -> None:
        self.policy = policy or FloodPolicy()

    @property
    def lookback(self) -> timedelta:
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
        stream_ids: Mapping[int, int] | None = None,
        target_observed_at: set[datetime] | None = None,
    ) -> list[CellSignal]:
        return evaluate_cell(
            cell_id,
            observations,
            self.policy,
            stream_ids=stream_ids,
            target_observed_at=target_observed_at,
        )
