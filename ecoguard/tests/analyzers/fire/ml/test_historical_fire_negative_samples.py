from datetime import datetime, timedelta, timezone

from ecoguard.analyzers.fire.ml.build_historical_fire_negative_samples import (
    FirmsIncident,
    FirmsSpaceTimeIndex,
    generate_negative_samples,
    haversine_km,
    parse_timestamp,
)


REFERENCE_TIME = datetime(2024, 6, 15, 10, tzinfo=timezone.utc)


def incident(identifier, timestamp, lat=31.9, lon=34.9, duration_hours=0):
    start = parse_timestamp(timestamp)
    return FirmsIncident(identifier, start, start + timedelta(hours=duration_hours), lat, lon)


def positive(identifier="positive-1", settlement="רמלה", code="8500"):
    return {
        "candidate_id": identifier,
        "start_timestamp": "2024-06-15T10:00:00Z",
        "centroid_latitude": "31.9",
        "centroid_longitude": "34.9",
        "settlement": settlement,
        "settlement_lamas_code": code,
        "ground_truth_status": "supported",
    }


def incident_history():
    return [
        incident("early", "2023-01-01T00:00:00Z", 33.0, 35.5),
        incident("reference", "2024-06-15T10:00:00Z"),
        incident("late", "2026-08-01T00:00:00Z", 30.0, 34.5),
    ]


def test_no_negative_within_spatial_and_temporal_exclusion():
    index = FirmsSpaceTimeIndex(incident_history())
    assert index.is_excluded(31.9, 34.9, REFERENCE_TIME + timedelta(hours=72), 5.0, 72.0)
    assert index.is_excluded(31.91, 34.9, REFERENCE_TIME, 5.0, 72.0)


def test_spatially_close_is_allowed_when_safely_far_in_time():
    index = FirmsSpaceTimeIndex(incident_history())
    assert not index.is_excluded(31.9, 34.9, REFERENCE_TIME + timedelta(hours=73), 5.0, 72.0)


def test_temporally_close_is_allowed_when_safely_far_in_space():
    index = FirmsSpaceTimeIndex(incident_history())
    assert haversine_km(31.9, 34.9, 32.0, 35.0) > 5
    assert not index.is_excluded(32.0, 35.0, REFERENCE_TIME, 5.0, 72.0)


def test_full_incident_duration_and_adjacent_margin_are_excluded():
    ongoing = incident("ongoing", "2024-06-10T00:00:00Z", duration_hours=48)
    index = FirmsSpaceTimeIndex([ongoing])
    assert index.is_excluded(31.9, 34.9, ongoing.end + timedelta(hours=72), 5.0, 72.0)
    assert not index.is_excluded(31.9, 34.9, ongoing.end + timedelta(hours=73), 5.0, 72.0)


def test_generation_avoids_positive_timestamp_and_duplicates():
    rows = generate_negative_samples([positive()], incident_history(), seed=7)
    assert len(rows) == 2
    assert all(row["sample_timestamp"] != "2024-06-15T10:00:00Z" for row in rows)
    identities = {(row["latitude"], row["longitude"], row["sample_timestamp"]) for row in rows}
    assert len(identities) == len(rows)


def test_deterministic_output_with_fixed_seed():
    first = generate_negative_samples([positive()], incident_history(), seed=99)
    second = generate_negative_samples([positive()], reversed(incident_history()), seed=99)
    assert first == second


def test_same_area_and_month_are_preferred():
    rows = generate_negative_samples([positive()], incident_history(), seed=2)
    same_centroid = next(row for row in rows if row["sample_generation_method"].startswith("same_centroid"))
    assert same_centroid["latitude"] == 31.9
    assert same_centroid["longitude"] == 34.9
    assert any(row["sample_month"] == 6 for row in rows)


def test_unlocated_open_area_sample_does_not_invent_settlement():
    rows = generate_negative_samples([positive(settlement="", code="")], incident_history(), seed=4)
    assert rows
    assert all(row["settlement"] == "" for row in rows)
    assert all(row["settlement_lamas_code"] == "" for row in rows)
    assert all(row["official_month_support"] == "false" for row in rows)


def test_fire_label_is_exact_zero_proxy_semantics():
    rows = generate_negative_samples([positive()], incident_history(), seed=11)
    assert rows
    assert all(row["fire_label"] == 0 for row in rows)
    index = FirmsSpaceTimeIndex(incident_history())
    assert all(
        not index.is_excluded(
            float(row["latitude"]),
            float(row["longitude"]),
            parse_timestamp(row["sample_timestamp"]),
            5.0,
            72.0,
        )
        for row in rows
    )
