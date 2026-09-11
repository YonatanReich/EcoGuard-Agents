from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.pilots.build_fire_risk_strong_event_case_study import (
    TIER_B,
    discover_tier_b_events,
    resolve_reference_time,
    score_rows,
    trajectory_events,
)
from research.datasets.build_historical_environmental_features import PriorFirmsIndex, historical_fire_features
from research.datasets.build_historical_fire_negative_samples import FirmsIncident
from research.training.train_fire_prediction_landcover_terrain_models import FULL_FEATURES


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def test_discovers_and_deduplicates_official_and_telegram_tier_b(tmp_path):
    strong = tmp_path / "strong.csv"
    telegram = tmp_path / "telegram.csv"
    _write(strong, [{
        "ground_truth_event_id": "official-1", "label_confidence_tier": TIER_B,
        "source_name": "authority", "source_url_or_identifier": "official://1",
        "event_timestamp_start": "2024-01-02", "timestamp_precision": "date",
        "latitude": "32.0", "longitude": "35.0", "location_name": "forest",
        "location_precision": "area_name", "label_confidence_score": "0.8",
        "firms_candidate_id": "firms-1", "firms_match_status": "matched",
        "firms_match_count": "1", "firms_spatial_distance_km": "1", "firms_temporal_gap_hours": "0", "notes": "",
    }])
    _write(telegram, [{
        "telegram_event_id": "telegram-1", "label_confidence_tier": TIER_B,
        "channel_name": "Police", "telegram_source_url_or_identifier": "telegram://1",
        "message_timestamp": "2025-01-02T10:00:00+00:00", "timestamp_precision": "minute",
        "latitude": "32.1", "longitude": "35.1", "location_text": "open area",
        "location_precision": "locality", "firms_candidate_id": "firms-2",
        "firms_match_status": "matched", "firms_match_count": "1",
        "firms_distance_km": "1", "firms_time_gap_hours": "0", "notes": "",
    }])
    events = discover_tier_b_events(strong, telegram)
    assert [event["event_id"] for event in events] == ["official-1", "telegram-1"]
    assert {event["source_type"] for event in events} == {"official_report", "verified_telegram"}


def test_date_only_reference_uses_retained_firms_time_without_upgrading_precision():
    timestamp = datetime(2024, 7, 5, 12, 30, tzinfo=timezone.utc)
    incident = FirmsIncident("firms-1", timestamp, timestamp, 32.0, 35.0)
    event = {"timestamp_precision": "date", "firms_candidate_id": "firms-1"}
    reference, basis, reason = resolve_reference_time(event, {"firms-1": incident})
    assert reference == timestamp
    assert basis == "matched_firms_acquisition_for_date_only_event"
    assert reason == ""
    assert event["timestamp_precision"] == "date"


def test_prior_firms_features_exclude_current_candidate_and_future_observations():
    event_time = datetime(2025, 1, 10, 12, tzinfo=timezone.utc)
    incidents = [
        FirmsIncident("prior", event_time - timedelta(days=2), event_time - timedelta(days=2), 32.0, 35.0),
        FirmsIncident("current", event_time - timedelta(minutes=5), event_time, 32.0, 35.0),
        FirmsIncident("future", event_time + timedelta(minutes=1), event_time + timedelta(hours=1), 32.0, 35.0),
    ]
    features = historical_fire_features(
        PriorFirmsIndex(incidents), 32.0, 35.0, event_time,
        excluded_candidate_ids=["current"],
    )
    assert features["fires_within_5km_previous_30d"] == 1
    assert features["fires_within_10km_previous_90d"] == 1
    assert features["days_since_previous_firms_candidate_within_10km"] == 2.0


def test_date_only_event_without_matched_candidate_is_incomplete():
    reference, basis, reason = resolve_reference_time(
        {"timestamp_precision": "date", "firms_candidate_id": "missing"}, {}
    )
    assert reference is None
    assert basis == ""
    assert "no retained matched FIRMS candidate" in reason


class _FakeAgent:
    calibration_metadata = {
        "calibration": {"method": "sigmoid"},
        "low_medium_threshold": 0.2,
        "medium_high_threshold": 0.6,
    }

    def predict(self, payload):
        assert list(payload) == list(FULL_FEATURES)
        return {"status": "ok", "risk_score": 0.7, "risk_level": "high", "model_version": "test", "main_factors": []}


def test_scoring_uses_exact_44_feature_schema_and_is_deterministic():
    row = {"event_id": "event", "feature_status": "complete", **{name: 1.0 for name in FULL_FEATURES}}
    first = score_rows([row], _FakeAgent())
    second = score_rows([row], _FakeAgent())
    assert first == second
    assert len(FULL_FEATURES) == 44
    assert first[0]["risk_level"] == "high"


def test_trajectory_timestamps_are_strictly_before_precise_event_time():
    event_time = datetime(2025, 8, 24, 11, 28, 2, tzinfo=timezone.utc)
    events = trajectory_events([{
        "event_id": "telegram-1", "timestamp_precision": "minute",
        "event_timestamp": event_time.isoformat(), "firms_candidate_id": "firms-1",
    }])
    timestamps = [datetime.fromisoformat(event["event_timestamp"]) for event in events]
    assert timestamps == [event_time - timedelta(hours=12), event_time - timedelta(hours=6), event_time - timedelta(hours=3)]
    assert all(timestamp < event_time for timestamp in timestamps)
