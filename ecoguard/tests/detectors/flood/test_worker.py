"""Cursor and atomic-success behaviour of the flood worker."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ecoguard.collection.flood.radar import (
    RadarCellMapping,
    RadarFrame,
    records_from_frame,
)
from ecoguard.database.repositories.flood_worker import (
    CommitResult,
    CursorPosition,
    PendingBatch,
)
from ecoguard.detectors.flood import worker
from ecoguard.detectors.flood.rules import (
    HYDROMETRIC_SOURCE,
    RADAR_SOURCE,
    RAIN_GAUGE_SOURCE,
)


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0040-c0012"


class Repository:
    def __init__(self, pending, active_events=None, station_contexts=None):
        self.pending = pending
        self.active_events = active_events or {}
        self.station_contexts = station_contexts or {}
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

    def load_station_contexts(self, source_station_ids):
        return {
            station_id: self.station_contexts[station_id]
            for station_id in source_station_ids
            if station_id in self.station_contexts
        }

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


def _radar_observation(observation_id, observed_at, rate_mm_h):
    """Build the normalized row produced by the numeric radar collector."""
    frame = RadarFrame(
        observed_at=observed_at,
        projection="EPSG:4326",
        xscale_m=600.0,
        yscale_m=600.0,
        data_mm_h=np.array([[rate_mm_h]], dtype=np.float32),
        source_name=f"controlled-{observation_id}.PPI.h5",
    )
    mapping = RadarCellMapping(CELL, 32.0, 34.8, 0, 1, 0, 1)
    record = records_from_frame(
        frame,
        [mapping],
        include_dry_cells={CELL},
    )[0]
    return {
        "id": observation_id,
        "source": RADAR_SOURCE,
        "ingested_at": observed_at,
        **record,
    }


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
    candidate = result.candidates[0]
    assert candidate["event_key"].startswith("flood:rain:")
    assert candidate["detected"] is True
    assert candidate["is_urban"] is True
    assert candidate["location"]["source"] == "rain_gauge"
    assert candidate["trigger"] == "urban_rain_10m"
    assert candidate["reasoning"]["primary_signal"] == candidate["trigger"]
    assert candidate["rainfall_evidence"]["rainfall_10m_mm"] == 9.0
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


def test_gauge_event_keeps_detector_reasoning_location_and_downstream_route():
    observations = []
    for observation_id, minutes, discharge in ((30, -10, 9.0), (31, 0, 32.0)):
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
                            "name_he": "תחנת נחל בדיקה",
                            "name_en": "Test stream gauge",
                            "discharge_m3s": discharge,
                            "water_height_m": 1.3,
                            "flow_start_water_level_m": 1.0,
                            "flow_threshold_2y_m3s": 10.0,
                            "flow_threshold_5y_m3s": 20.0,
                            "flow_threshold_10y_m3s": 30.0,
                            "flow_threshold_20y_m3s": 40.0,
                            "flow_threshold_50y_m3s": 50.0,
                            "flow_threshold_100y_m3s": 60.0,
                            "latitude": 32.01,
                            "longitude": 34.81,
                        }
                    ]
                },
            }
        )
    route = {
        "status": "complete",
        "confidence": "high",
        "method": "water_authority_draining_water_id",
        "origin_water_source_id": 9001,
        "segment_count": 3,
        "segments": [
            {"hop": 0, "water_source_id": 9001},
            {"hop": 1, "water_source_id": 9002},
            {"hop": 2, "water_source_id": 9003},
        ],
        "termination": "declared_network_end",
        "limitations": [],
    }
    repository = Repository(
        PendingBatch(
            observations,
            [CursorPosition(HYDROMETRIC_SOURCE, NOW, 31)],
        ),
        station_contexts={
            50: {
                "source_station_id": 50,
                "hydrometric_station_id": 7,
                "name_he": "תחנת נחל בדיקה",
                "name_en": "Test stream gauge",
                "basin_id": 12,
                "basin_name_he": "אגן בדיקה",
                "basin_name_en": "Test basin",
                "stream_context": {
                    "matched": True,
                    "confidence": "high",
                    "stream": {"water_source_id": 9001},
                },
                "downstream_route": route,
            }
        },
    )

    result = worker.FloodDetectorWorker(repository).run_once()

    event = result.candidates[0]
    assert event["event_key"] == f"flood:gauge:{CELL}:50"
    assert event["location"] == {
        "known": True,
        "latitude": 32.01,
        "longitude": 34.81,
        "source": "hydrometric_station",
        "uncertainty_m": 100.0,
    }
    assert event["is_urban"] is True
    assert event["station"]["hydrometric_station_id"] == 7
    assert event["drainage_basin"]["basin_id"] == 12
    assert [
        segment["water_source_id"]
        for segment in event["downstream_route"]["segments"]
    ] == [9001, 9002, 9003]
    assert event["reasoning"]["primary_signal"] == (
        "gauge_discharge_rating_curve"
    )
    assert event["hydrological_evidence"][
        "highest_crossed_return_period_years"
    ] == 10


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


def test_numeric_radar_pipeline_opens_then_resolves_an_urban_event():
    """Exercise collector output, cursor commits and the complete lifecycle."""
    wet = _radar_observation(20, NOW, 108.0)  # 9 mm in one five-minute frame.
    opening_cursor = CursorPosition(RADAR_SOURCE, NOW, 20)
    opening_repository = Repository(PendingBatch([wet], [opening_cursor]))

    opening = worker.FloodDetectorWorker(opening_repository).run_once()

    assert opening.candidates[0]["severity_hint"] == "moderate"
    assert opening_repository.commits[0][2] == [opening_cursor]
    stored_candidate = opening_repository.commits[0][0][0]
    active_event = {
        "event_key": stored_candidate.event_key,
        "candidate_key": stored_candidate.candidate_key,
        "cell_id": stored_candidate.cell_id,
        "opened_at": stored_candidate.observed_at,
        "trigger": stored_candidate.trigger,
        "evidence": stored_candidate.evidence,
    }

    dry_observations = [
        _radar_observation(
            21 + index,
            NOW + timedelta(minutes=minutes),
            0.0,
        )
        for index, minutes in enumerate((30, 40, 50, 60))
    ]
    last_dry = dry_observations[-1]
    closing_cursor = CursorPosition(
        RADAR_SOURCE,
        last_dry["ingested_at"],
        last_dry["id"],
    )
    closing_repository = Repository(
        PendingBatch(dry_observations, [closing_cursor]),
        {CELL: [active_event]},
    )

    closing = worker.FloodDetectorWorker(closing_repository).run_once()

    assert closing.candidates == []
    assert closing.resolutions == [
        {
            "event_key": stored_candidate.event_key,
            "candidate_key": stored_candidate.candidate_key,
            "event_type": "flood",
            "cell_id": CELL,
            "observed_at": last_dry["observed_at"],
            "status": "resolved",
            "reason": "rain_below_exit_threshold",
            "evidence": {
                "rainfall_10m_mm": 0.0,
                "rainfall_1h_mm": 0.0,
                "rainfall_6h_mm": 0.0,
                "rainfall_24h_mm": 0.0,
            },
        }
    ]
    assert closing_repository.commits[0][2] == [closing_cursor]
