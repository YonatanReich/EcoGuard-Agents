from datetime import datetime, timedelta, timezone

import pytest

from agents.flood_detection_agent import (
    FloodDetectionAgent,
    FloodDetectionPolicy,
)


NOW = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(
        self,
        histories=None,
        error=None,
        stream_network=None,
        stream_error=None,
        collector_runs=None,
        collector_error=None,
    ):
        self.histories = histories or []
        self.error = error
        self.stream_network = (
            stream_network
            if stream_network is not None
            else [
                {
                    "stream_id": 21,
                    "object_id": 301,
                    "name_he": "נחל בדיקה",
                    "water_source_id": 9001,
                    "draining_water_id": 9002,
                    "draining_water_name": "נחל מוצא",
                    "representative_latitude": 30.09001,
                    "representative_longitude": 34.09001,
                },
                {
                    "stream_id": 22,
                    "object_id": 302,
                    "name_he": "נחל מוצא",
                    "water_source_id": 9002,
                    "draining_water_id": 9003,
                    "draining_water_name": "הים",
                    "representative_latitude": 30.09002,
                    "representative_longitude": 34.09002,
                },
                {
                    "stream_id": 23,
                    "object_id": 303,
                    "name_he": "הים",
                    "water_source_id": 9003,
                    "draining_water_id": None,
                    "draining_water_name": None,
                    "representative_latitude": 30.09003,
                    "representative_longitude": 34.09003,
                },
            ]
        )
        self.stream_error = stream_error
        self.stream_network_calls = 0
        self.collector_runs = (
            collector_runs
            if collector_runs is not None
            else {
                "water_authority_hydrometric_observations": {
                    "source": "water_authority_hydrometric_observations",
                    "started_at": NOW - timedelta(minutes=6),
                    "finished_at": NOW - timedelta(minutes=5),
                    "status": "ok",
                    "rows_written": 12,
                    "error": None,
                },
                "water_authority_rainfall_observations": {
                    "source": "water_authority_rainfall_observations",
                    "started_at": NOW - timedelta(minutes=6),
                    "finished_at": NOW - timedelta(minutes=5),
                    "status": "ok",
                    "rows_written": 18,
                    "error": None,
                },
            }
        )
        self.collector_error = collector_error
        self.collector_run_sources = None
        self.observed_since = None
        self.rainfall_since = None
        self.as_of = None
        self.stream_candidate_radius_m = None
        self.stream_candidate_limit = None

    def load_station_histories(
        self,
        *,
        observed_since,
        rainfall_since,
        as_of,
        stream_candidate_radius_m,
        stream_candidate_limit,
    ):
        self.observed_since = observed_since
        self.rainfall_since = rainfall_since
        self.as_of = as_of
        self.stream_candidate_radius_m = stream_candidate_radius_m
        self.stream_candidate_limit = stream_candidate_limit
        if self.error is not None:
            raise self.error
        return self.histories

    def load_stream_network(self):
        self.stream_network_calls += 1
        if self.stream_error is not None:
            raise self.stream_error
        return self.stream_network

    def load_latest_collector_runs(self, *, sources):
        self.collector_run_sources = sources
        if self.collector_error is not None:
            raise self.collector_error
        return self.collector_runs


def observation(minutes_ago, discharge, height):
    return {
        "observed_at": NOW - timedelta(minutes=minutes_ago),
        "discharge_m3s": discharge,
        "water_height_m": height,
    }


def network_stream(water_source_id, draining_water_id, *, object_id=None):
    return {
        "stream_id": object_id or water_source_id,
        "object_id": object_id or water_source_id,
        "name_he": f"נחל {water_source_id}",
        "water_source_id": water_source_id,
        "main_catchment_code": "12",
        "main_catchment_name": "אגן בדיקה",
        "draining_water_id": draining_water_id,
        "draining_water_name": (
            f"נחל {draining_water_id}"
            if draining_water_id is not None
            else None
        ),
        "representative_latitude": 30.0 + water_source_id / 100_000,
        "representative_longitude": 34.0 + water_source_id / 100_000,
    }


def station_history(**overrides):
    observations = [
        observation(30, 30.0, 1.30),
        observation(20, 38.0, 1.42),
        observation(10, 50.0, 1.58),
    ]
    snapshot = {
        "source_station_id": 49,
        "hydrometric_station_id": 7,
        **observations[-1],
        "observations": observations,
        "station_name_he": "תחנת בדיקה",
        "station_name_en": "Test station",
        "latitude": 31.5,
        "longitude": 34.8,
        "flow_start_water_level_m": 1.2,
        "flow_threshold_2y_m3s": 17.0,
        "flow_threshold_5y_m3s": 37.0,
        "flow_threshold_10y_m3s": 48.0,
        "flow_threshold_20y_m3s": 60.0,
        "flow_threshold_50y_m3s": 90.0,
        "flow_threshold_100y_m3s": 120.0,
        "basin_id": 12,
        "basin_name_he": "אגן בדיקה",
        "basin_name_en": "Test basin",
        "rainfall_evidence": [
            {
                "source_station_id": 101,
                "latest_observed_at": NOW - timedelta(minutes=10),
                "rainfall_10m_mm": 2.0,
                "rainfall_1h_mm": 8.0,
                "rainfall_6h_mm": 31.0,
                "rainfall_24h_mm": 40.0,
            }
        ],
        "stream_candidates": [
            {
                "stream_id": 21,
                "object_id": 301,
                "name_he": "נחל בדיקה",
                "water_source_id": 9001,
                "main_catchment_code": "12",
                "main_catchment_name": "אגן בדיקה",
                "draining_water_id": 9002,
                "draining_water_name": "נחל מוצא",
                "distance_m": 18.4,
            }
        ],
    }
    snapshot.update(overrides)
    return snapshot


def test_detects_high_flow_with_stable_event_key_and_separate_intensity():
    repository = FakeRepository([station_history()])
    agent = FloodDetectionAgent(repository)

    result = agent.detect_floods(now=NOW)

    assert repository.observed_since == NOW - timedelta(minutes=90)
    assert repository.rainfall_since == NOW - timedelta(
        hours=24, minutes=30
    )
    assert repository.as_of == NOW
    assert repository.stream_candidate_radius_m == 2_000.0
    assert repository.stream_candidate_limit == 20
    assert repository.collector_run_sources == (
        "water_authority_hydrometric_observations",
        "water_authority_rainfall_observations",
    )
    assert result["detected"] is True
    assert result["assessed_station_count"] == 1
    event = result["detected_events"][0]
    assert event["event_key"] == "flood:water_authority:49"
    assert event["detection_state"] == "observed_high_flow"
    assert event["flow_intensity"] == "high"
    assert event["confidence"] == "high"
    assert event["hydrological_evidence"][
        "highest_crossed_return_period_years"
    ] == 10
    assert event["hydrological_evidence"]["flow_started"] is True
    assert event["drainage_basin"]["basin_id"] == 12
    assert event["stream_context"] == {
        "association": "same_drainage_basin",
        "matched": True,
        "confidence": "high",
        "method": "same_basin_name_and_distance",
        "candidate_count": 1,
        "distinct_candidate_count": 1,
        "stream": {
            "stream_id": 21,
            "object_id": 301,
            "name_he": "נחל בדיקה",
            "water_source_id": 9001,
            "main_catchment_code": "12",
            "main_catchment_name": "אגן בדיקה",
            "draining_water_id": 9002,
            "draining_water_name": "נחל מוצא",
            "distance_m": 18.4,
            "name_matches_station": True,
        },
        "nearest_candidate": None,
        "warnings": [],
    }
    assert event["downstream_route"]["status"] == "complete"
    assert event["downstream_route"]["termination"] == (
        "declared_network_end"
    )
    assert [
        segment["water_source_id"]
        for segment in event["downstream_route"]["segments"]
    ] == [9001, 9002, 9003]
    assert event["downstream_route"]["segments"][1][
        "representative_location"
    ] == {"latitude": 30.09002, "longitude": 34.09002}
    assert repository.stream_network_calls == 1
    assert result["source_status"]["hydrometric_observations"] == {
        "status": "success",
        "collector_source": "water_authority_hydrometric_observations",
        "latest_collection_status": "ok",
        "latest_started_at": "2026-09-14T09:54:00+00:00",
        "latest_finished_at": "2026-09-14T09:55:00+00:00",
        "latest_rows_written": 12,
        "latest_run_has_error": False,
        "cached_data_available": True,
        "cached_data_fresh": True,
        "cache_coverage": "fresh",
        "cached_station_count": 1,
        "fresh_station_count": 1,
        "latest_observed_at": "2026-09-14T09:50:00+00:00",
    }
    assert event["rainfall_evidence"][0]["rainfall_6h_mm"] == 31.0
    assert event["rainfall_context"] == {
        "association": "same_drainage_basin",
        "basin_id": 12,
        "station_count": 1,
        "stations_with_observations": 1,
        "fresh_station_count": 1,
        "latest_observation_at": "2026-09-14T09:50:00+00:00",
        "is_fresh": True,
        "recent_rain_detected": True,
        "limitations": [
            "same_basin_does_not_prove_upstream_subcatchment",
            "rainfall_has_not_yet_been_compared_with_local_idf",
        ],
        "maximum_10m_mm": 2.0,
        "mean_10m_mm": 2.0,
        "maximum_1h_mm": 8.0,
        "mean_1h_mm": 8.0,
        "maximum_6h_mm": 31.0,
        "mean_6h_mm": 31.0,
        "maximum_24h_mm": 40.0,
        "mean_24h_mm": 40.0,
    }


def test_persistent_q2_crossing_is_likely_flood_wave():
    observations = [
        observation(30, 16.0, 1.25),
        observation(20, 18.0, 1.25),
        observation(10, 18.0, 1.25),
    ]
    history = station_history(
        **observations[-1], observations=observations
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    event = result["detected_events"][0]
    assert event["detection_state"] == "flood_wave_likely"
    assert event["flow_intensity"] == "low"
    assert event["hydrological_evidence"][
        "q2_persistence_observations"
    ] == 2


def test_single_q2_crossing_creates_watch_not_confirmed_detection():
    observations = [
        observation(30, 15.0, 1.10),
        observation(20, 15.0, 1.10),
        observation(10, 18.0, 1.22),
    ]
    history = station_history(
        **observations[-1], observations=observations
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is False
    assert result["detected_events"] == []
    watch = result["watch_events"][0]
    assert watch["detected"] is False
    assert watch["detection_state"] == "flood_watch"
    assert watch["confidence"] == "low"


def test_current_station_below_threshold_without_rapid_rise_is_clear():
    observations = [
        observation(30, 10.0, 1.25),
        observation(20, 10.0, 1.25),
        observation(10, 10.0, 1.25),
    ]
    history = station_history(
        **observations[-1], observations=observations
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is False
    assert result["detected_events"] == []
    assert result["watch_events"] == []
    assert result["assessed_station_count"] == 1


def test_rapid_persistent_rise_below_q2_is_detected_separately():
    observations = [
        observation(30, 10.0, 1.21),
        observation(20, 12.0, 1.31),
        observation(10, 14.0, 1.41),
    ]
    history = station_history(
        **observations[-1], observations=observations
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    event = result["detected_events"][0]
    assert event["detection_state"] == "rapid_flow_detected"
    assert event["flow_intensity"] == "low"
    assert event["hydrological_evidence"]["rapid_stage_rise"] is True


def test_station_without_thresholds_uses_basin_rain_as_corroboration():
    observations = [
        observation(30, None, 0.90),
        observation(20, None, 1.02),
        observation(10, None, 1.14),
    ]
    history = station_history(
        **observations[-1],
        observations=observations,
        flow_start_water_level_m=1.0,
        flow_threshold_2y_m3s=None,
        flow_threshold_5y_m3s=None,
        flow_threshold_10y_m3s=None,
        flow_threshold_20y_m3s=None,
        flow_threshold_50y_m3s=None,
        flow_threshold_100y_m3s=None,
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is True
    event = result["detected_events"][0]
    assert event["detection_state"] == "flood_wave_likely"
    assert event["flow_intensity"] == "unranked"
    assert event["confidence"] == "high"
    assert event["hydrological_evidence"]["rapid_stage_rise"] is True
    assert event["hydrological_evidence"]["threshold_status"] == "unavailable"
    assert "recent_rainfall_in_same_drainage_basin" in event["reasons"]


def test_stale_basin_rain_does_not_raise_detection_confidence():
    observations = [
        observation(30, None, 0.90),
        observation(20, None, 1.02),
        observation(10, None, 1.14),
    ]
    history = station_history(
        **observations[-1],
        observations=observations,
        flow_start_water_level_m=1.0,
        flow_threshold_2y_m3s=None,
        flow_threshold_5y_m3s=None,
        flow_threshold_10y_m3s=None,
        flow_threshold_20y_m3s=None,
        flow_threshold_50y_m3s=None,
        flow_threshold_100y_m3s=None,
        rainfall_evidence=[
            {
                "source_station_id": 101,
                "latest_observed_at": NOW - timedelta(minutes=31),
                "rainfall_10m_mm": 2.0,
                "rainfall_1h_mm": 8.0,
                "rainfall_6h_mm": 31.0,
                "rainfall_24h_mm": 40.0,
            }
        ],
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    event = result["detected_events"][0]
    assert event["confidence"] == "medium"
    assert event["rainfall_context"]["is_fresh"] is False
    assert event["rainfall_context"]["maximum_1h_mm"] is None
    assert "recent_rainfall_in_same_drainage_basin" not in event["reasons"]


def test_basin_rain_uses_maximum_and_mean_without_summing_gauges():
    history = station_history(
        rainfall_evidence=[
            {
                "source_station_id": 101,
                "latest_observed_at": NOW - timedelta(minutes=10),
                "rainfall_10m_mm": 2.0,
                "rainfall_1h_mm": 8.0,
                "rainfall_6h_mm": 31.0,
                "rainfall_24h_mm": 40.0,
            },
            {
                "source_station_id": 102,
                "latest_observed_at": NOW - timedelta(minutes=20),
                "rainfall_10m_mm": 1.0,
                "rainfall_1h_mm": 4.0,
                "rainfall_6h_mm": 21.0,
                "rainfall_24h_mm": 30.0,
            },
        ]
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    context = result["detected_events"][0]["rainfall_context"]
    assert context["station_count"] == 2
    assert context["fresh_station_count"] == 2
    assert context["maximum_1h_mm"] == 8.0
    assert context["mean_1h_mm"] == 6.0


def test_active_unknown_station_without_enough_trend_remains_explicit():
    unknown = station_history(
        source_station_id=999,
        hydrometric_station_id=None,
        latitude=None,
        longitude=None,
        observations=[observation(10, 50.0, 1.7)],
        flow_threshold_2y_m3s=None,
        flow_threshold_5y_m3s=None,
        flow_threshold_10y_m3s=None,
        flow_threshold_20y_m3s=None,
        flow_threshold_50y_m3s=None,
        flow_threshold_100y_m3s=None,
    )
    agent = FloodDetectionAgent(FakeRepository([unknown]))

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is None
    assert result["assessed_station_count"] == 0
    assert result["unassessed_stations"][0]["reason"] == (
        "active_flow_without_valid_discharge_thresholds_or_trend"
    )
    assert result["unassessed_stations"][0]["threshold_status"] == (
        "unavailable"
    )


def test_non_monotonic_thresholds_are_not_used_for_intensity():
    observations = [
        observation(30, None, 0.90),
        observation(20, None, 1.02),
        observation(10, None, 1.14),
    ]
    history = station_history(
        **observations[-1],
        observations=observations,
        flow_start_water_level_m=1.0,
        flow_threshold_20y_m3s=1156.0,
        flow_threshold_50y_m3s=176.0,
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    event = result["detected_events"][0]
    assert event["detection_state"] == "flood_wave_likely"
    assert event["flow_intensity"] == "unranked"
    assert event["hydrological_evidence"]["threshold_status"] == (
        "non_monotonic"
    )


def test_duplicate_history_timestamps_do_not_fake_persistence():
    same_time = NOW - timedelta(minutes=10)
    duplicates = [
        {
            "observed_at": same_time,
            "discharge_m3s": 18.0,
            "water_height_m": 1.22,
        },
        {
            "observed_at": same_time,
            "discharge_m3s": 19.0,
            "water_height_m": 1.23,
        },
    ]
    history = station_history(
        observed_at=same_time,
        discharge_m3s=19.0,
        water_height_m=1.23,
        observations=duplicates,
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is False
    assert result["watch_events"][0]["detection_state"] == "flood_watch"


def test_stale_station_makes_an_empty_scan_inconclusive():
    stale = station_history(
        observed_at=NOW - timedelta(minutes=31),
        observations=[observation(31, 50.0, 1.7)],
    )
    agent = FloodDetectionAgent(FakeRepository([stale]))

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is None
    assert result["unassessed_stations"][0]["reason"] == "stale_observation"


def test_height_only_below_flow_start_is_clear_without_thresholds():
    observations = [
        observation(30, None, 0.8),
        observation(20, None, 0.8),
        observation(10, None, 0.8),
    ]
    history = station_history(
        **observations[-1],
        observations=observations,
        flow_start_water_level_m=1.0,
        flow_threshold_2y_m3s=None,
        flow_threshold_5y_m3s=None,
        flow_threshold_10y_m3s=None,
        flow_threshold_20y_m3s=None,
        flow_threshold_50y_m3s=None,
        flow_threshold_100y_m3s=None,
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is False
    assert result["assessed_station_count"] == 1


def test_database_failure_is_not_reported_as_no_flood():
    agent = FloodDetectionAgent(
        FakeRepository(error=RuntimeError("database unavailable"))
    )

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is None
    assert result["metadata"]["collection_status"] == "failed"
    assert result["source_status"]["hydrology_database"] == "failed"


def test_failed_collector_with_fresh_cache_is_degraded_not_unavailable():
    repository = FakeRepository(
        [station_history()],
        collector_runs={
            "water_authority_hydrometric_observations": {
                "source": "water_authority_hydrometric_observations",
                "started_at": NOW - timedelta(minutes=2),
                "finished_at": NOW - timedelta(minutes=1),
                "status": "failed",
                "rows_written": None,
                "error": "provider timeout",
            }
        },
    )
    agent = FloodDetectionAgent(repository)

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is True
    health = result["source_status"]["hydrometric_observations"]
    assert health["status"] == "degraded"
    assert health["latest_collection_status"] == "failed"
    assert health["cached_data_fresh"] is True
    assert health["latest_run_has_error"] is True


def test_failed_collector_with_stale_cache_remains_inconclusive():
    stale = station_history(
        observed_at=NOW - timedelta(minutes=31),
        observations=[observation(31, 50.0, 1.7)],
    )
    repository = FakeRepository(
        [stale],
        collector_runs={
            "water_authority_hydrometric_observations": {
                "source": "water_authority_hydrometric_observations",
                "started_at": NOW - timedelta(minutes=2),
                "finished_at": NOW - timedelta(minutes=1),
                "status": "failed",
                "rows_written": None,
                "error": "provider timeout",
            }
        },
    )
    agent = FloodDetectionAgent(repository)

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is None
    health = result["source_status"]["hydrometric_observations"]
    assert health["status"] == "failed"
    assert health["cache_coverage"] == "stale"
    assert health["cached_data_fresh"] is False


def test_missing_collector_run_is_reported_as_never_run():
    agent = FloodDetectionAgent(
        FakeRepository([station_history()], collector_runs={})
    )

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is True
    assert result["source_status"]["hydrometric_observations"][
        "status"
    ] == "never_run"
    assert result["source_status"]["rainfall_observations"][
        "status"
    ] == "never_run"


def test_collector_history_failure_does_not_erase_detection():
    agent = FloodDetectionAgent(
        FakeRepository(
            [station_history()],
            collector_error=RuntimeError("collector history unavailable"),
        )
    )

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is True
    assert result["source_status"]["hydrometric_observations"][
        "status"
    ] == "unknown"
    assert result["source_status"]["rainfall_observations"][
        "status"
    ] == "unknown"
    assert result["source_errors"]["collector_runs"] == (
        "RuntimeError: collector history unavailable"
    )


def test_empty_database_is_inconclusive_not_clear():
    agent = FloodDetectionAgent(FakeRepository([]))

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is None
    assert result["input_station_count"] == 0
    assert result["assessed_station_count"] == 0


def test_stream_name_can_select_a_slightly_farther_same_basin_candidate():
    history = station_history(
        station_name_he="ירקון-תחנת בדיקה",
        stream_candidates=[
            {
                "stream_id": 31,
                "object_id": 401,
                "name_he": "איילון",
                "water_source_id": 8001,
                "distance_m": 40.0,
            },
            {
                "stream_id": 32,
                "object_id": 402,
                "name_he": "ירקון",
                "water_source_id": 8002,
                "distance_m": 90.0,
            },
        ],
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    context = agent.detect_floods(now=NOW)["detected_events"][0][
        "stream_context"
    ]

    assert context["matched"] is True
    assert context["confidence"] == "high"
    assert context["method"] == "same_basin_name_and_distance"
    assert context["stream"]["water_source_id"] == 8002


def test_very_close_stream_can_match_without_a_name_match():
    history = station_history(
        stream_candidates=[
            {
                "stream_id": 31,
                "object_id": 401,
                "name_he": "איילון",
                "water_source_id": 8001,
                "distance_m": 80.0,
            }
        ]
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    context = agent.detect_floods(now=NOW)["detected_events"][0][
        "stream_context"
    ]

    assert context["matched"] is True
    assert context["confidence"] == "medium"
    assert context["method"] == "same_basin_distance_only"
    assert context["warnings"] == [
        "station_and_stream_names_do_not_match"
    ]


def test_distance_only_stream_beyond_100m_remains_unresolved():
    history = station_history(
        stream_candidates=[
            {
                "stream_id": 31,
                "object_id": 401,
                "name_he": "איילון",
                "water_source_id": 8001,
                "distance_m": 150.0,
            }
        ]
    )
    repository = FakeRepository([history])
    agent = FloodDetectionAgent(repository)

    event = agent.detect_floods(now=NOW)["detected_events"][0]
    context = event["stream_context"]

    assert context["matched"] is False
    assert context["confidence"] == "low"
    assert context["stream"] is None
    assert context["nearest_candidate"]["water_source_id"] == 8001
    assert context["warnings"] == [
        "station_and_stream_names_do_not_match",
        "distance_only_match_is_not_reliable",
    ]
    assert event["downstream_route"]["termination"] == (
        "origin_stream_unmatched"
    )
    assert repository.stream_network_calls == 0


def test_similarly_close_distinct_named_streams_are_ambiguous():
    history = station_history(
        station_name_he="אלפא בטא-תחנה",
        stream_candidates=[
            {
                "stream_id": 31,
                "object_id": 401,
                "name_he": "אלפא",
                "water_source_id": 8001,
                "distance_m": 20.0,
            },
            {
                "stream_id": 32,
                "object_id": 402,
                "name_he": "בטא",
                "water_source_id": 8002,
                "distance_m": 45.0,
            },
        ],
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    context = agent.detect_floods(now=NOW)["detected_events"][0][
        "stream_context"
    ]

    assert context["matched"] is False
    assert context["confidence"] == "low"
    assert context["stream"] is None
    assert context["warnings"] == ["multiple_similarly_close_streams"]


def test_segments_with_same_water_source_are_not_false_ambiguity():
    history = station_history(
        stream_candidates=[
            {
                "stream_id": 31,
                "object_id": 401,
                "name_he": "נחל בדיקה",
                "water_source_id": 8001,
                "distance_m": 20.0,
            },
            {
                "stream_id": 32,
                "object_id": 402,
                "name_he": "נחל בדיקה",
                "water_source_id": 8001,
                "distance_m": 35.0,
            },
        ],
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    context = agent.detect_floods(now=NOW)["detected_events"][0][
        "stream_context"
    ]

    assert context["matched"] is True
    assert context["distinct_candidate_count"] == 1
    assert context["stream"]["object_id"] == 401


def test_stream_beyond_reliable_distance_is_reported_not_linked():
    history = station_history(
        stream_candidates=[
            {
                "stream_id": 31,
                "object_id": 401,
                "name_he": "נחל בדיקה",
                "water_source_id": 8001,
                "distance_m": 1_200.0,
            }
        ]
    )
    agent = FloodDetectionAgent(FakeRepository([history]))

    context = agent.detect_floods(now=NOW)["detected_events"][0][
        "stream_context"
    ]

    assert context["matched"] is False
    assert context["nearest_candidate"]["distance_m"] == 1_200.0
    assert context["warnings"] == [
        "nearest_stream_beyond_reliable_distance"
    ]


def test_downstream_route_stops_at_missing_network_node():
    repository = FakeRepository(
        [station_history()],
        stream_network=[network_stream(9001, 9002)],
    )
    agent = FloodDetectionAgent(repository)

    route = agent.detect_floods(now=NOW)["detected_events"][0][
        "downstream_route"
    ]

    assert route["status"] == "partial"
    assert route["termination"] == "downstream_stream_missing_from_network"
    assert route["segment_count"] == 1
    assert route["segments"][0]["matched_object_id"] == 301


def test_downstream_route_detects_a_cycle_without_looping():
    repository = FakeRepository(
        [station_history()],
        stream_network=[
            network_stream(9001, 9002),
            network_stream(9002, 9001),
        ],
    )
    agent = FloodDetectionAgent(repository)

    route = agent.detect_floods(now=NOW)["detected_events"][0][
        "downstream_route"
    ]

    assert route["status"] == "partial"
    assert route["confidence"] == "low"
    assert route["termination"] == "cycle_detected"
    assert [item["water_source_id"] for item in route["segments"]] == [
        9001,
        9002,
    ]


def test_conflicting_duplicate_topology_is_not_guessed():
    repository = FakeRepository(
        [station_history()],
        stream_network=[
            network_stream(9001, 9002, object_id=301),
            network_stream(9001, 9003, object_id=302),
            network_stream(9002, None),
            network_stream(9003, None),
        ],
    )
    agent = FloodDetectionAgent(repository)

    route = agent.detect_floods(now=NOW)["detected_events"][0][
        "downstream_route"
    ]

    assert route["status"] == "partial"
    assert route["confidence"] == "low"
    assert route["termination"] == "conflicting_downstream_connections"
    assert route["segments"][0]["topology_conflict"] is True
    assert route["segments"][0]["object_ids"] == [301, 302]


def test_stream_network_failure_does_not_erase_flood_detection():
    repository = FakeRepository(
        [station_history()],
        stream_error=RuntimeError("stream table unavailable"),
    )
    agent = FloodDetectionAgent(repository)

    result = agent.detect_floods(now=NOW)

    assert result["detected"] is True
    assert result["source_status"]["stream_network"] == "failed"
    assert result["source_errors"] == {
        "stream_network": "RuntimeError: stream table unavailable"
    }
    route = result["detected_events"][0]["downstream_route"]
    assert route["status"] == "unavailable"
    assert route["termination"] == "stream_network_unavailable"


def test_downstream_route_respects_the_configured_hop_limit():
    repository = FakeRepository(
        [station_history()],
        stream_network=[
            network_stream(9001, 9002),
            network_stream(9002, 9003),
            network_stream(9003, None),
        ],
    )
    agent = FloodDetectionAgent(
        repository,
        FloodDetectionPolicy(max_downstream_hops=1),
    )

    route = agent.detect_floods(now=NOW)["detected_events"][0][
        "downstream_route"
    ]

    assert route["status"] == "partial"
    assert route["termination"] == "maximum_hops_reached"
    assert [item["water_source_id"] for item in route["segments"]] == [
        9001,
        9002,
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"max_observation_age": timedelta(0)},
            "max_observation_age must be positive",
        ),
        (
            {
                "max_observation_age": timedelta(minutes=30),
                "history_window": timedelta(minutes=30),
            },
            "history_window must be longer than max_observation_age",
        ),
        (
            {"minimum_consecutive_rises": 0},
            "minimum_consecutive_rises must be positive",
        ),
        (
            {"rainfall_history_window": timedelta(0)},
            "rainfall_history_window must be positive",
        ),
        (
            {"max_rainfall_age": timedelta(0)},
            "max_rainfall_age must be positive",
        ),
        (
            {"stream_candidate_radius_m": 0},
            "stream_candidate_radius_m must be positive",
        ),
        (
            {"stream_candidate_limit": 1},
            "stream_candidate_limit must be at least two",
        ),
        (
            {
                "strong_stream_distance_m": 101,
                "max_reliable_stream_distance_m": 100,
            },
            "max_reliable_stream_distance_m must be at least",
        ),
        (
            {
                "max_reliable_stream_distance_m": 1_001,
                "stream_candidate_radius_m": 1_000,
            },
            "stream_candidate_radius_m must be at least",
        ),
        (
            {"stream_ambiguity_distance_m": -1},
            "stream_ambiguity_distance_m cannot be negative",
        ),
        (
            {"stream_name_override_distance_factor": 0.5},
            "stream_name_override_distance_factor must be at least one",
        ),
        (
            {"max_downstream_hops": 0},
            "max_downstream_hops must be positive",
        ),
    ],
)
def test_rejects_invalid_policy(kwargs, message):
    with pytest.raises(ValueError, match=message):
        FloodDetectionPolicy(**kwargs)
