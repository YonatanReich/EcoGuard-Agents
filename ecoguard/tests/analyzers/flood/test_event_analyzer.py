"""Contract tests for deterministic Flood event analysis."""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.analyzers.flood.event_analyzer import FloodEventAnalyzer


AT = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
THRESHOLDS = [20.0, 35.0, 50.0, 80.0, 120.0, 170.0]


def signal(
    *,
    station_id=417,
    cell_id="31.75:35.20",
    observed_at=AT,
    severity=3,
    previous_discharge=52.0,
    current_discharge=60.0,
    stream_id=82,
    latitude=31.75,
    longitude=35.2,
):
    return {
        "cell_id": cell_id,
        "observed_at": observed_at.isoformat(),
        "hazard": "flood",
        "variable": "discharge",
        "value": current_discharge,
        "unit": "m3/s",
        "source": "water_authority_hydrometric_observations",
        "confidence": 0.9,
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "precision_m": 100.0,
            "method": "hydrometric_station",
        },
        "evidence": {
            "station_id": station_id,
            "source_station_id": station_id,
            "stream_id": stream_id,
            "timestamp": observed_at.isoformat(),
            "current_discharge": current_discharge,
            "severity_level": severity,
            "threshold_vector_m3s": THRESHOLDS,
            "recent_discharges_m3s": [previous_discharge, current_discharge],
        },
    }


def incident(*signals):
    return {
        "id": "INC-FLOOD-1",
        "status": "open",
        "primary_hazard": "flood",
        "hazards": ["flood"],
        "signals": list(signals),
    }


def analyzer():
    return FloodEventAnalyzer(clock=lambda: AT + timedelta(hours=1))


def test_initial_signal_establishes_q10_state_without_external_calls():
    result = analyzer().analyze(incident(signal()))

    assert result.status == "success"
    assert result.current_state.severity_level == 3
    assert result.current_state.return_period_years == 10
    assert result.current_state.alert_level == "active"
    assert result.progression_assessment.trend == "rising"
    assert result.progression_assessment.discharge_change_m3s == 8.0
    assert result.change_assessment.change_type == "initial"
    assert result.change_assessment.material_change is True


def test_q10_to_q20_is_an_explicit_material_escalation():
    first = signal(observed_at=AT, severity=3, current_discharge=60.0)
    second = signal(
        observed_at=AT + timedelta(minutes=10),
        severity=4,
        previous_discharge=60.0,
        current_discharge=84.2,
    )

    result = analyzer().analyze(incident(first, second))

    assert result.current_state.severity_level == 4
    assert result.current_state.return_period_years == 20
    assert result.change_assessment.change_type == "escalated"
    assert result.change_assessment.material_change is True
    assert result.change_assessment.previous_severity_level == 3
    assert result.change_assessment.current_severity_level == 4
    assert result.change_assessment.threshold_transition == "Q10_to_Q20"
    assert result.change_assessment.reasons == [
        "official_return_period_threshold_increased"
    ]


def test_rising_discharge_inside_the_same_q_band_is_not_material():
    first = signal(observed_at=AT, severity=4, current_discharge=82.0)
    second = signal(
        observed_at=AT + timedelta(minutes=10),
        severity=4,
        previous_discharge=82.0,
        current_discharge=90.0,
    )

    result = analyzer().analyze(incident(first, second))

    assert result.progression_assessment.trend == "rising"
    assert result.change_assessment.change_type == "no_material_change"
    assert result.change_assessment.material_change is False
    assert result.change_assessment.threshold_transition is None


def test_lower_official_threshold_is_reported_as_deescalation():
    first = signal(observed_at=AT, severity=5, current_discharge=125.0)
    second = signal(
        observed_at=AT + timedelta(minutes=10),
        severity=4,
        previous_discharge=125.0,
        current_discharge=110.0,
    )

    result = analyzer().analyze(incident(first, second))

    assert result.progression_assessment.trend == "falling"
    assert result.change_assessment.change_type == "deescalated"
    assert result.change_assessment.threshold_transition == "Q50_to_Q20"


def test_new_station_and_cell_are_a_material_footprint_update():
    first = signal(observed_at=AT, severity=4, current_discharge=85.0)
    second = signal(
        station_id=418,
        cell_id="31.80:35.25",
        observed_at=AT + timedelta(minutes=10),
        severity=4,
        previous_discharge=82.0,
        current_discharge=85.0,
        stream_id=83,
        latitude=31.8,
        longitude=35.25,
    )

    result = analyzer().analyze(incident(first, second))

    assert result.current_state.station_count == 2
    assert result.change_assessment.change_type == "updated"
    assert result.change_assessment.material_change is True
    assert result.change_assessment.new_station_ids == [418]
    assert result.change_assessment.new_cell_ids == ["31.80:35.25"]
    assert result.change_assessment.reasons == [
        "new_hydrometric_station_observed",
        "incident_spatial_footprint_expanded",
    ]


def test_event_severity_uses_latest_state_per_station_and_worst_current_station():
    station_417_q50 = signal(observed_at=AT, severity=5, current_discharge=130.0)
    station_418_q20 = signal(
        station_id=418,
        cell_id="31.80:35.25",
        observed_at=AT + timedelta(minutes=10),
        severity=4,
        previous_discharge=82.0,
        current_discharge=85.0,
        stream_id=83,
        latitude=31.8,
        longitude=35.25,
    )

    result = analyzer().analyze(incident(station_417_q50, station_418_q20))

    assert result.current_state.primary_station_id == 417
    assert result.current_state.severity_level == 5
    assert result.change_assessment.change_type == "updated"


def test_duplicate_station_timestamp_does_not_create_false_progression():
    original = signal()
    retried = signal(current_discharge=61.0, previous_discharge=53.0)

    result = analyzer().analyze(incident(original, retried))

    assert result.duplicate_signal_count == 1
    assert result.change_assessment.change_type == "initial"
    assert result.current_state.stations[0].current_discharge_m3s == 61.0


def test_malformed_flood_signal_is_visible_but_does_not_destroy_valid_analysis():
    malformed = signal(observed_at=AT - timedelta(minutes=10))
    malformed["evidence"]["severity_level"] = 99

    result = analyzer().analyze(incident(malformed, signal()))

    assert result.status == "partial"
    assert result.invalid_signal_count == 1
    assert "malformed Flood signal" in result.evidence_gaps[-1]


def test_missing_signals_returns_unavailable_instead_of_safe_defaults():
    result = analyzer().analyze(incident())

    assert result.status == "unavailable"
    assert result.current_state is None
    assert result.progression_assessment is None
    assert result.change_assessment is None


def test_contract_contains_no_unused_precipitation_inputs():
    serialized = analyzer().analyze(incident(signal())).model_dump_json().lower()

    assert "radar" not in serialized
    assert "idf" not in serialized
    assert "rain" not in serialized


def test_naive_clock_is_rejected():
    service = FloodEventAnalyzer(clock=lambda: datetime(2026, 9, 20, 12, 0))

    with pytest.raises(ValueError, match="UTC offset"):
        service.analyze(incident(signal()))
