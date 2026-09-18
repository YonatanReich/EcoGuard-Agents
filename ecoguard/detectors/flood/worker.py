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
from ecoguard.detectors.flood.station_rules import (
    FLOOD_SOURCES,
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

    def load_active_events(
        self, cell_ids: Sequence[str]
    ) -> dict[str, list[dict[str, Any]]]: ...

    def load_stream_ids(
        self, source_station_ids: Sequence[int]
    ) -> dict[int, int]: ...

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
        window = self.repository.load_window(
            cell_ids,
            FLOOD_SOURCES,
            observed_since=earliest_new - self.agent.lookback,
            observed_through=latest_new,
        )
        source_station_ids = sorted(
            {
                int(station["source_station_id"])
                for observation in window
                for station in (observation.get("payload") or {}).get(
                    "stations", []
                )
                if station.get("source_station_id") is not None
            }
        )
        stream_ids = self.repository.load_stream_ids(source_station_ids)
        active_events = self.repository.load_active_events(cell_ids)
        by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for observation in window:
            by_cell[observation["cell_id"]].append(observation)
        candidates: list[FloodCandidate] = []
        resolutions: list[FloodResolution] = []
        for cell_id in cell_ids:
            evaluation = self.agent.evaluate(
                cell_id=cell_id,
                observations=by_cell.get(cell_id, []),
                stream_ids=stream_ids,
                active_events=active_events.get(cell_id, []),
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
