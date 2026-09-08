"""Offline EA-311 engineering-policy tests; no provider or coordinator calls."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agents.air_pollution_anomaly_schemas import AirPollutionAnomaly
from agents.air_pollution_correlation import (
    PollutionCorrelationCandidate, PollutionCorrelationPolicy,
    PollutionCorrelationResult, compare_pollution_candidates, correlation_candidate,
)
from agents.air_pollution_spatial_schemas import SpatiallyEnrichedAirPollutionAnomaly

NOW = datetime(2026, 9, 8, 12, 29, tzinfo=timezone.utc)


def candidate(identifier="a", pollutant="PM2.5", minutes=0, latitude=32.1,
              longitude=34.8, station="s1", channel="c1", context=None):
    observed = NOW + timedelta(minutes=minutes)
    anomaly = AirPollutionAnomaly(
        detection_id=identifier, observed_at=observed, detected_at=observed,
        location={"latitude": latitude, "longitude": longitude},
        pollutant_observations=[] if pollutant is None else [
            {"pollutant": pollutant, "value": 20.0, "unit": "ppb"}],
        severity="medium", confidence=0.6, explanation="Synthetic detector evidence",
        sources=[{"source_id": "provider", "source_name": "Test source",
                  "metadata": {"station_id": station, "channel_id": channel}}],
    )
    if context is None:
        return correlation_candidate(anomaly)
    return correlation_candidate(SpatiallyEnrichedAirPollutionAnomaly(
        anomaly=anomaly, spatial_context={
            "location": anomaly.location, "lookup_radius_km": 2.0,
            "status": "success", "source": "OpenStreetMap / Overpass API", **context},
    ))


def test_exact_duplicate_retains_both_inputs():
    item = candidate()
    before = item.model_dump(round_trip=True)
    result = compare_pollution_candidates(item, item)
    assert result.candidate_match and result.duplicate_kind == "exact"
    assert result.left == result.right == item
    assert item.model_dump(round_trip=True) == before
    assert result.spatial_distance_km == result.temporal_distance_seconds == 0


def test_same_station_observation_with_distinct_detection_ids():
    result = compare_pollution_candidates(candidate(), candidate("b"))
    assert result.duplicate_kind == "same_station_observation"
    assert result.left.anomaly.detection_id != result.right.anomaly.detection_id


def test_near_duplicate_is_only_candidate():
    result = compare_pollution_candidates(candidate(), candidate("b", minutes=0.5, station="s2"))
    assert result.duplicate_kind == "near_duplicate_candidate"
    assert result.limitations


def test_close_same_pollutant_across_bucket_boundary():
    a, b = candidate(), candidate("b", minutes=2, longitude=34.81)
    assert a.time_bucket_utc != b.time_bucket_utc
    result = compare_pollution_candidates(a, b)
    assert result.candidate_match and result.duplicate_kind == "none"
    assert result.temporal_distance_seconds == 120
    assert 0.8 < result.spatial_distance_km < 1.1


@pytest.mark.parametrize("kwargs,signal", [
    ({"latitude": 33.1}, "outside_distance_window"),
    ({"minutes": 180}, "outside_time_window"),
    ({"pollutant": "SO2"}, "pollutant_missing_or_incompatible"),
])
def test_unrelated_candidates(kwargs, signal):
    result = compare_pollution_candidates(candidate(), candidate("b", **kwargs))
    assert not result.candidate_match
    assert result.duplicate_kind == "none"
    assert signal in result.conflicting_signals


def test_compatible_particulate_family_not_duplicate():
    result = compare_pollution_candidates(candidate(), candidate("b", pollutant="PM10"))
    assert result.candidate_match
    assert "compatible_particulate_family" in result.matching_signals
    assert result.duplicate_kind == "none"


@pytest.mark.parametrize("status", ["success", "partial"])
def test_settlement_overlap_support_only(status):
    context = {"status": status, "nearby_settlements": [
        {"name": "Test settlement", "osm_type": "node", "osm_id": 42}]}
    a, b = candidate(context=context), candidate("b", minutes=2, context=context)
    result = compare_pollution_candidates(a, b)
    assert "overlapping_geographic_context" in result.matching_signals
    assert result.shared_geographic_features
    distant = candidate("c", latitude=33.1, context=context)
    assert not compare_pollution_candidates(a, distant).candidate_match


def test_names_alone_not_shared_identity():
    context = {"nearby_settlements": [{"name": "Repeated name"}]}
    assert not compare_pollution_candidates(
        candidate(context=context), candidate("b", context=context)).shared_geographic_features


def test_unavailable_context_is_not_used():
    context = {"status": "unavailable", "nearby_roads": [
        {"osm_type": "way", "osm_id": 2}]}
    result = compare_pollution_candidates(candidate(context=context), candidate("b", context=context))
    assert not result.shared_geographic_features
    assert any("unavailable" in text for text in result.limitations)


def test_missing_context_does_not_block_location_match():
    result = compare_pollution_candidates(candidate(), candidate("b", minutes=2))
    assert result.candidate_match
    assert any("absent" in text for text in result.limitations)


def test_missing_pollutants_not_inferred():
    result = compare_pollution_candidates(candidate(pollutant=None), candidate("b"))
    assert not result.candidate_match


def test_timezone_equivalence_and_roundtrip():
    a = candidate()
    payload = a.model_dump(round_trip=True)
    payload["anomaly"]["observed_at"] = "2026-09-08T14:29:00+02:00"
    b = PollutionCorrelationCandidate.model_validate(payload)
    assert compare_pollution_candidates(a, b).temporal_distance_seconds == 0
    result = compare_pollution_candidates(a, b)
    assert PollutionCorrelationResult.model_validate_json(result.model_dump_json(round_trip=True)) == result


@pytest.mark.parametrize("field,value", [("latitude", 91.0), ("longitude", float("nan"))])
def test_invalid_coordinates_rejected(field, value):
    with pytest.raises(ValidationError):
        candidate(**{field: value})


def test_invalid_time_and_context_rejected():
    payload = candidate().model_dump(round_trip=True)
    payload["anomaly"]["observed_at"] = "2026-09-08T12:29:00"
    with pytest.raises(ValidationError):
        PollutionCorrelationCandidate.model_validate(payload)
    with pytest.raises(ValidationError):
        candidate(context={"location": {"latitude": 31.0, "longitude": 34.8}})


def test_provenance_and_detection_confidence_preserved():
    a, b = candidate(), candidate("b", channel="other")
    result = compare_pollution_candidates(a, b)
    assert result.left.anomaly == a.anomaly
    assert result.right.anomaly == b.anomaly
    assert result.left.station_channels == [("provider", "s1", "c1")]
    assert result.duplicate_kind != "same_station_observation"
    assert result.left.anomaly.confidence == 0.6


@pytest.mark.parametrize("field", ["emergency_required", "dispatch", "response_plan", "allocated_resources"])
def test_downstream_fields_rejected(field):
    with pytest.raises(ValidationError):
        PollutionCorrelationCandidate.model_validate({**candidate().model_dump(round_trip=True), field: True})


def test_policy_configurable_and_validated():
    assert not compare_pollution_candidates(candidate(), candidate("b", minutes=3),
        policy=PollutionCorrelationPolicy(maximum_minutes=2.0)).candidate_match
    with pytest.raises(ValidationError):
        PollutionCorrelationPolicy(maximum_distance_km=-1.0)
    with pytest.raises(ValidationError):
        PollutionCorrelationPolicy(near_duplicate_seconds=9999.0)


def test_symmetric_distance_across_antimeridian():
    a, b = candidate(longitude=179.99), candidate("b", longitude=-179.99)
    forward = compare_pollution_candidates(a, b)
    reverse = compare_pollution_candidates(b, a)
    assert forward.candidate_match == reverse.candidate_match is True
    assert forward.spatial_distance_km == pytest.approx(reverse.spatial_distance_km)


def test_comparison_offline(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("No network permitted")

    monkeypatch.setattr(socket, "socket", forbidden)
    assert compare_pollution_candidates(candidate(), candidate("b")).candidate_match
