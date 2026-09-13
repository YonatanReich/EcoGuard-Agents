from datetime import datetime, timezone

from ecoguard.research.datasets.build_historical_environmental_features import (
    PriorFirmsIndex,
    collect_elevations,
    enrich_rows,
    historical_fire_features,
)
from ecoguard.research.datasets.build_historical_fire_negative_samples import FirmsIncident


def incident(identifier, timestamp, lat=31.9, lon=34.9):
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return FirmsIncident(identifier, parsed, parsed, lat, lon)


def row(identifier="sample", timestamp="2025-06-15T12:00:00Z", settlement=""):
    return {"sample_id": identifier, "timestamp": timestamp, "latitude": "31.9", "longitude": "34.9", "settlement": settlement, "settlement_lamas_code": "", "fire_label": "0"}


def test_history_excludes_current_and_future_incidents():
    timestamp = datetime(2025, 6, 15, 12, tzinfo=timezone.utc)
    index = PriorFirmsIndex([
        incident("past", "2025-06-14T12:00:00Z"),
        incident("current", "2025-06-15T12:00:00Z"),
        incident("future", "2025-06-16T12:00:00Z"),
    ])
    features = historical_fire_features(index, 31.9, 34.9, timestamp)
    assert features["fires_within_5km_previous_30d"] == 1
    assert features["fires_within_10km_previous_90d"] == 1
    assert features["fires_within_25km_previous_365d"] == 1
    assert features["days_since_previous_firms_candidate_within_10km"] == 1


def test_history_radius_and_window_semantics():
    timestamp = datetime(2025, 6, 15, 12, tzinfo=timezone.utc)
    index = PriorFirmsIndex([
        incident("near-recent", "2025-06-01T12:00:00Z"),
        incident("mid", "2025-04-01T12:00:00Z", 31.96, 34.9),
        incident("far", "2025-01-01T12:00:00Z", 32.05, 34.9),
        incident("old", "2023-01-01T12:00:00Z"),
    ])
    features = historical_fire_features(index, 31.9, 34.9, timestamp)
    assert features["fires_within_5km_previous_30d"] == 1
    assert features["fires_within_10km_previous_90d"] == 2
    assert features["fires_within_25km_previous_365d"] == 3
    assert features["days_since_previous_firms_candidate_within_10km"] == 14


def test_unlocated_open_area_gets_coordinate_features():
    rows = enrich_rows([row()], [incident("past", "2025-06-01T12:00:00Z")], {"31.900000,34.900000": 123.0})
    assert rows[0]["settlement"] == ""
    assert rows[0]["elevation_m"] == 123.0
    assert rows[0]["fires_within_5km_previous_30d"] == 1
    assert rows[0]["elevation_collection_status"] == "success"


def test_deterministic_row_preservation():
    source = [row("b", "2025-06-16T12:00:00Z"), row("a")]
    elevations = {"31.900000,34.900000": 100.0}
    incidents = [incident("past", "2025-01-01T00:00:00Z")]
    first = enrich_rows(source, incidents, elevations)
    second = enrich_rows(source, reversed(incidents), elevations)
    assert first == second
    assert [item["sample_id"] for item in first] == ["b", "a"]
    assert len(first) == len(source)


class Response:
    status_code = 200
    def json(self): return {"elevation": [10.0, 20.0]}


class Session:
    def __init__(self): self.calls = 0
    def get(self, *args, **kwargs): self.calls += 1; return Response()


def test_elevation_cache_resume(tmp_path):
    rows = [row("a"), {**row("b"), "latitude": "32.0", "longitude": "35.0"}]
    cache = tmp_path / "elevation.json"
    session = Session()
    first = collect_elevations(rows, cache_path=cache, session=session, sleep=lambda _: None, logger=lambda _: None)
    second_session = Session()
    second = collect_elevations(rows, cache_path=cache, session=second_session, sleep=lambda _: None, logger=lambda _: None)
    assert first == second
    assert session.calls == 1
    assert second_session.calls == 0
