"""Cursor-driven flood detector worker; scheduling remains outside this module."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from ecoguard.database.repositories.flood_worker import (
    CommitResult,
    DEFAULT_BATCH_SIZE,
    CursorPosition,
    FloodWorkerRepository,
    PendingBatch,
)
from ecoguard.detectors.flood.detection_agent import FloodDetectionAgent
from ecoguard.detectors.flood.rules import (
    FLOOD_SOURCES,
    HYDROMETRIC_SOURCE,
    RADAR_SOURCE,
    RAIN_GAUGE_SOURCE,
    FloodCandidate,
    FloodResolution,
)


class FloodRepository(Protocol):
    def load_pending(
        self, sources: Sequence[str], *, limit_per_source: int
    ) -> PendingBatch: ...

    def load_window(
        self,
        cell_ids: Sequence[str],
        sources: Sequence[str],
        *,
        observed_since: Any,
        observed_through: Any,
    ) -> list[dict[str, Any]]: ...

    def load_context(self, cell_ids: Sequence[str]) -> dict[str, dict[str, Any]]: ...

    def load_basin_rain_window(
        self,
        basin_ids: Sequence[int],
        sources: Sequence[str],
        *,
        observed_since: Any,
        observed_through: Any,
    ) -> list[dict[str, Any]]: ...

    def load_baselines(
        self, source_station_ids: Sequence[int]
    ) -> dict[tuple[int, int], dict[str, Any]]: ...

    def load_active_events(
        self, cell_ids: Sequence[str]
    ) -> dict[str, list[dict[str, Any]]]: ...

    def commit_success(
        self,
        candidates: Sequence[FloodCandidate],
        resolutions: Sequence[FloodResolution],
        high_watermarks: Sequence[CursorPosition],
    ) -> CommitResult: ...


@dataclass(frozen=True)
class FloodRunResult:
    observations_processed: int
    cells_evaluated: int
    candidates: list[dict[str, Any]]
    resolutions: list[dict[str, Any]]

    @property
    def no_op(self) -> bool:
        return self.observations_processed == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "no_op": self.no_op,
            "observations_processed": self.observations_processed,
            "cells_evaluated": self.cells_evaluated,
            "candidates": self.candidates,
            "resolutions": self.resolutions,
        }


def _hydrometric_station_ids(
    observations: Sequence[dict[str, Any]],
) -> list[int]:
    return sorted(
        {
            int(station["source_station_id"])
            for observation in observations
            if observation["source"] == HYDROMETRIC_SOURCE
            for station in (observation.get("payload") or {}).get("stations", [])
        }
    )


class FloodDetectorWorker:
    """Read new cells, evaluate a full window, then commit cursors on success."""

    def __init__(
        self,
        repository: FloodRepository | None = None,
        *,
        agent: FloodDetectionAgent | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.repository = repository or FloodWorkerRepository()
        self.agent = agent or FloodDetectionAgent()
        self.batch_size = batch_size

    def run_once(self) -> FloodRunResult:
        pending = self.repository.load_pending(
            FLOOD_SOURCES, limit_per_source=self.batch_size
        )
        if not pending.observations:
            return FloodRunResult(0, 0, [], [])

        fresh = [
            row for row in pending.observations if self.agent.accepts_pending(row)
        ]
        if not fresh:
            self.repository.commit_success([], [], pending.high_watermarks)
            return FloodRunResult(len(pending.observations), 0, [], [])

        cell_ids = sorted({row["cell_id"] for row in fresh})
        earliest_new = min(row["observed_at"] for row in fresh)
        latest_new = max(row["observed_at"] for row in fresh)
        context = self.repository.load_context(cell_ids)
        window = self.repository.load_window(
            cell_ids,
            FLOOD_SOURCES,
            observed_since=earliest_new - self.agent.lookback,
            observed_through=latest_new,
        )
        basin_ids = sorted(
            {
                int(item["drainage_basin_id"])
                for item in context.values()
                if item.get("drainage_basin_id") is not None
            }
        )
        basin_window = self.repository.load_basin_rain_window(
            basin_ids,
            (RAIN_GAUGE_SOURCE, RADAR_SOURCE),
            observed_since=earliest_new - self.agent.lookback,
            observed_through=latest_new,
        )
        baselines = self.repository.load_baselines(
            _hydrometric_station_ids(window)
        )
        active_events = self.repository.load_active_events(cell_ids)
        by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for observation in window:
            by_cell[observation["cell_id"]].append(observation)
        by_basin: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for observation in basin_window:
            by_basin[int(observation["drainage_basin_id"])].append(observation)

        candidates: list[FloodCandidate] = []
        resolutions: list[FloodResolution] = []
        for cell_id in cell_ids:
            evaluation = self.agent.evaluate(
                cell_id=cell_id,
                observations=by_cell.get(cell_id, []),
                context=context.get(cell_id),
                baselines=baselines,
                active_events=active_events.get(cell_id, []),
                catchment_observations=by_basin.get(
                    context.get(cell_id, {}).get("drainage_basin_id"), []
                ),
            )
            candidates.extend(evaluation.candidates)
            resolutions.extend(evaluation.resolutions)

        # This is the only write in the worker. If evaluation raised, or this
        # transaction fails, no cursor advances and the same rows are retried.
        committed = self.repository.commit_success(
            candidates, resolutions, pending.high_watermarks
        )
        return FloodRunResult(
            observations_processed=len(pending.observations),
            cells_evaluated=len(cell_ids),
            candidates=[
                candidate.public()
                for candidate in candidates
                if candidate.candidate_key in committed.inserted_candidate_keys
            ],
            resolutions=[
                resolution.public()
                for resolution in resolutions
                if resolution.event_key in committed.resolved_event_keys
            ],
        )


def run_flood_detector() -> dict[str, Any]:
    """Convenient timer entry point without coupling the worker to a scheduler."""
    return FloodDetectorWorker().run_once().as_dict()
