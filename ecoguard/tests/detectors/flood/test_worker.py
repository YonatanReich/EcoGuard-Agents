"""Cursor and atomic-success behaviour of the flood worker."""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.database.repositories.flood_worker import (
    CommitResult,
    CursorPosition,
    PendingBatch,
)
from ecoguard.detectors.flood import worker
from ecoguard.detectors.flood.rules import HYDROMETRIC_SOURCE, RAIN_GAUGE_SOURCE


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0040-c0012"


class Repository:
    def __init__(self, pending, active_events=None):
        self.pending = pending
        self.active_events = active_events or {}
        self.commits = []

    def load_pending(self, sources, *, limit_per_source):
        return self.pending

    def load_window(self, cell_ids, sources, *, observed_since, observed_through):
        return self.pending.observations

    def load_context(self, cell_ids):
        return {
            CELL: {
                "cell_id": CELL,
                "latitude": 32.0,
                "longitude": 34.8,
                "drainage_basin_id": 1,
                "built_up_fraction": 0.8,
                "is_urban": True,
                "urban_classification_status": "classified",
                "urban_sample_count": 9,
                "slope_deg": 0.0,
                "distance_to_stream_m": 1000.0,
            }
        }

    def load_basin_rain_window(
        self, basin_ids, sources, *, observed_since, observed_through
    ):
        return []

    def load_baselines(self, source_station_ids):
        return {}

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


def _pending():
    observation = {
        "id": 9,
        "source": RAIN_GAUGE_SOURCE,
        "cell_id": CELL,
        "observed_at": NOW,
        "ingested_at": NOW,
        "payload": {
            "stations": [
                {
                    "source_station_id": 205,
                    "rainfall_mm": 9.0,
                    "latitude": 32.0,
                    "longitude": 34.8,
                }
            ]
        },
    }
    cursor = CursorPosition(RAIN_GAUGE_SOURCE, NOW, 9)
    return PendingBatch([observation], [cursor])


def test_no_new_observations_is_a_no_op():
    repository = Repository(PendingBatch([], []))

    result = worker.FloodDetectorWorker(repository).run_once()

    assert result.no_op is True
    assert result.candidates == []
    assert repository.commits == []


def test_success_emits_candidate_and_advances_consumed_cursor():
    repository = Repository(_pending())

    result = worker.FloodDetectorWorker(repository).run_once()

    assert result.no_op is False
    assert result.candidates[0]["confidence"] > 0
    assert result.candidates[0]["severity_hint"] == "moderate"
    assert result.candidates[0]["location_uncertainty_m"] == 2500.0
    assert set(result.candidates[0]) == {
        "candidate_key",
        "event_type",
        "cell_id",
        "observed_at",
        "latitude",
        "longitude",
        "confidence",
        "severity_hint",
        "location_uncertainty_m",
    }
    assert repository.commits[0][2] == _pending().high_watermarks


def test_evaluation_failure_does_not_advance_a_cursor():
    repository = Repository(_pending())

    class FailingAgent:
        lookback = timedelta(hours=30)

        def accepts_pending(self, observation):
            return True

        def evaluate(self, **kwargs):
            raise RuntimeError("bad data")

    with pytest.raises(RuntimeError, match="bad data"):
        worker.FloodDetectorWorker(repository, agent=FailingAgent()).run_once()

    assert repository.commits == []


def test_worker_resolves_an_active_gauge_event_and_advances_the_cursor():
    opened_at = NOW.replace(minute=0) - timedelta(minutes=30)
    observations = []
    for observation_id, minutes, discharge in ((10, -10, 7.5), (11, 0, 7.0)):
        observed_at = NOW + timedelta(minutes=minutes)
        observations.append(
            {
                "id": observation_id,
                "source": HYDROMETRIC_SOURCE,
                "cell_id": CELL,
                "observed_at": observed_at,
                "ingested_at": observed_at,
                "payload": {
                    "stations": [
                        {
                            "source_station_id": 50,
                            "discharge_m3s": discharge,
                            "water_height_m": 1.0,
                            "flow_threshold_2y_m3s": 10.0,
                            "latitude": 32.0,
                            "longitude": 34.8,
                        }
                    ]
                },
            }
        )
    pending = PendingBatch(
        observations,
        [CursorPosition(HYDROMETRIC_SOURCE, NOW, 11)],
    )
    event_key = f"flood:gauge:{CELL}:50"
    repository = Repository(
        pending,
        {
            CELL: [
                {
                    "event_key": event_key,
                    "candidate_key": "candidate-1",
                    "cell_id": CELL,
                    "opened_at": opened_at,
                    "trigger": "gauge_discharge_rating_curve",
                    "evidence": {"source_station_id": 50, "threshold": 10.0},
                }
            ]
        },
    )

    result = worker.FloodDetectorWorker(repository).run_once()

    assert result.candidates == []
    assert result.resolutions[0]["event_key"] == event_key
    assert result.resolutions[0]["status"] == "resolved"
    assert repository.commits[0][2] == pending.high_watermarks


def test_stale_backfill_advances_the_cursor_without_opening_an_event():
    pending = _pending()
    stale = {
        **pending.observations[0],
        "observed_at": NOW - timedelta(days=2),
        "ingested_at": NOW,
    }
    repository = Repository(PendingBatch([stale], pending.high_watermarks))

    result = worker.FloodDetectorWorker(repository).run_once()

    assert result.observations_processed == 1
    assert result.cells_evaluated == 0
    assert result.candidates == []
    assert repository.commits[0][2] == pending.high_watermarks
