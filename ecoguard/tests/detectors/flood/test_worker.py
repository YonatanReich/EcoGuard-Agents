"""Cursor and lifecycle behaviour of the minimal station detector."""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.database.repositories.flood_worker import (
    CommitResult,
    CursorPosition,
    PendingBatch,
)
from ecoguard.detectors.flood import worker
from ecoguard.detectors.flood.station_rules import HYDROMETRIC_SOURCE


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0040-c0012"


def _observation(observation_id: int, at: datetime, discharge: float) -> dict:
    return {
        "id": observation_id,
        "source": HYDROMETRIC_SOURCE,
        "cell_id": CELL,
        "observed_at": at,
        "ingested_at": at,
        "payload": {
            "stations": [
                {
                    "source_station_id": 50,
                    "discharge_m3s": discharge,
                    "latitude": 32.0,
                    "longitude": 34.8,
                    "flow_threshold_status": "complete_thresholds",
                    "flow_threshold_2y_m3s": 10.0,
                    "flow_threshold_5y_m3s": 20.0,
                    "flow_threshold_10y_m3s": 30.0,
                    "flow_threshold_20y_m3s": 40.0,
                    "flow_threshold_50y_m3s": 50.0,
                    "flow_threshold_100y_m3s": 60.0,
                }
            ]
        },
    }


class Repository:
    def __init__(self, pending: PendingBatch, active_events=None):
        self.pending = pending
        self.active_events = active_events or {}
        self.commits = []

    def load_pending(self, sources, *, limit_per_source):
        assert tuple(sources) == (HYDROMETRIC_SOURCE,)
        return self.pending

    def load_window(self, cell_ids, sources, *, observed_since, observed_through):
        return self.pending.observations

    def load_active_events(self, cell_ids):
        return {
            cell_id: self.active_events.get(cell_id, []) for cell_id in cell_ids
        }

    def commit_success(self, candidates, resolutions, high_watermarks):
        self.commits.append(
            (list(candidates), list(resolutions), list(high_watermarks))
        )
        return CommitResult(
            {candidate.candidate_key for candidate in candidates},
            {resolution.event_key for resolution in resolutions},
        )


def _pending(*discharges: float) -> PendingBatch:
    observations = [
        _observation(
            index + 1,
            NOW - timedelta(minutes=10 * (len(discharges) - index - 1)),
            discharge,
        )
        for index, discharge in enumerate(discharges)
    ]
    return PendingBatch(
        observations,
        [CursorPosition(HYDROMETRIC_SOURCE, NOW, len(observations))],
    )


def test_no_new_observations_is_a_no_op():
    repository = Repository(PendingBatch([], []))

    result = worker.FloodDetectorWorker(repository).run_once()

    assert result.no_op is True
    assert repository.commits == []


def test_worker_emits_compact_station_result_after_persistence():
    repository = Repository(_pending(21.0, 32.0))

    result = worker.FloodDetectorWorker(repository).run_once()

    assert result.candidates[0]["station_id"] == 50
    assert result.candidates[0]["timestamp"] == NOW
    assert result.candidates[0]["current_discharge"] == 32.0
    assert result.candidates[0]["severity_level"] == 3
    assert result.candidates[0]["trigger"] == "gauge_discharge_threshold"
    assert repository.commits[0][2] == repository.pending.high_watermarks


def test_one_high_reading_does_not_open_an_alert_but_advances_cursor():
    repository = Repository(_pending(19.0, 21.0))

    result = worker.FloodDetectorWorker(repository).run_once()

    assert result.candidates == []
    assert repository.commits[0][2] == repository.pending.high_watermarks


def test_worker_resolves_after_two_readings_below_q5_hysteresis():
    pending = _pending(15.9, 15.0)
    event_key = f"flood:gauge:{CELL}:50"
    repository = Repository(
        pending,
        {
            CELL: [
                {
                    "event_key": event_key,
                    "candidate_key": "candidate-1",
                    "cell_id": CELL,
                    "opened_at": NOW - timedelta(hours=1),
                    "trigger": "gauge_discharge_threshold",
                    "evidence": {"station_id": 50},
                }
            ]
        },
    )

    result = worker.FloodDetectorWorker(repository).run_once()

    assert result.candidates == []
    assert result.resolutions[0]["event_key"] == event_key
    assert result.resolutions[0]["evidence"]["exit_threshold_m3s"] == 16.0


def test_evaluation_failure_does_not_advance_a_cursor():
    repository = Repository(_pending(21.0, 22.0))

    class FailingAgent:
        lookback = timedelta(hours=6)

        def accepts_pending(self, observation):
            return True

        def evaluate(self, **kwargs):
            raise RuntimeError("bad data")

    with pytest.raises(RuntimeError, match="bad data"):
        worker.FloodDetectorWorker(repository, agent=FailingAgent()).run_once()

    assert repository.commits == []


def test_stale_backfill_advances_cursor_without_opening_an_alert():
    pending = _pending(21.0, 22.0)
    stale = [
        {**observation, "observed_at": NOW - timedelta(days=2), "ingested_at": NOW}
        for observation in pending.observations
    ]
    repository = Repository(PendingBatch(stale, pending.high_watermarks))

    result = worker.FloodDetectorWorker(repository).run_once()

    assert result.cells_evaluated == 0
    assert result.candidates == []
    assert repository.commits[0][2] == pending.high_watermarks
