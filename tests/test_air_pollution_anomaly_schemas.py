"""Focused validation tests for the air-pollution anomaly contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agents.air_pollution_anomaly_schemas import (
    CORE_AIR_POLLUTANTS,
    AirPollutionAnomaly,
)

OBSERVED_AT = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)
DETECTED_AT = OBSERVED_AT + timedelta(minutes=2)


def build_anomaly(**overrides) -> dict:
    """Return a complete valid anomaly payload with optional overrides."""
    payload = {
        "detection_id": "air-quality-network:station-17:20260907T080000Z",
        "anomaly_type": "air_pollution",
        "observed_at": OBSERVED_AT,
        "detected_at": DETECTED_AT,
        "location": {"latitude": 32.0853, "longitude": 34.7818},
        "affected_area": {
            "radius_m": 750.0,
            "description": "Approximate observation influence area",
        },
        "pollutant_observations": [
            {
                "pollutant": "PM2.5",
                "value": 48.2,
                "unit": "µg/m³",
                "observed_at": OBSERVED_AT,
                "source_id": "station-17",
            },
            {
                "pollutant": "NO2",
                "value": 61.0,
                "unit": "ppb",
                "observed_at": OBSERVED_AT,
                "source_id": "station-17",
            },
        ],
        "severity": "high",
        "confidence": 0.87,
        "explanation": "Several supplied observations deviate from the recent baseline.",
        "anomaly_reasons": ["PM2.5 exceeded the detector's anomaly threshold"],
        "sources": [
            {
                "source_id": "station-17",
                "source_name": "Municipal air-quality station 17",
                "source_type": "ground_sensor",
                "observed_at": OBSERVED_AT,
                "retrieved_at": DETECTED_AT,
            }
        ],
        "supporting_evidence": [
            {
                "evidence_id": "station-17:pm25:20260907T080000Z",
                "source_id": "station-17",
                "evidence_type": "pollutant_observation",
                "summary": "PM2.5 observation used by the anomaly detector.",
                "observed_at": OBSERVED_AT,
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_complete_pollution_anomaly():
    anomaly = AirPollutionAnomaly(**build_anomaly())

    assert anomaly.anomaly_type == "air_pollution"
    assert len(anomaly.pollutant_observations) == 2
    assert anomaly.severity == "high"


def test_anomaly_with_one_pollutant_and_missing_optional_context():
    anomaly = AirPollutionAnomaly(
        **build_anomaly(
            affected_area=None,
            pollutant_observations=[
                {"pollutant": "O3", "value": 74.0, "unit": "ppb"}
            ],
            supporting_evidence=[],
        )
    )

    assert anomaly.affected_area is None
    assert [item.pollutant for item in anomaly.pollutant_observations] == ["O3"]
    assert anomaly.supporting_evidence == []


@pytest.mark.parametrize(
    "pollutant",
    ["PM2.5", "PM10", "NO2", "NO", "NOx", "O3", "CO", "SO2"],
)
def test_core_israeli_monitoring_pollutants_are_supported(pollutant):
    anomaly = AirPollutionAnomaly(
        **build_anomaly(
            pollutant_observations=[
                {"pollutant": pollutant, "value": 12.5, "unit": "µg/m³"}
            ]
        )
    )

    assert anomaly.pollutant_observations[0].pollutant == pollutant
    assert pollutant in CORE_AIR_POLLUTANTS


def test_known_pollutant_alias_is_normalized():
    anomaly = AirPollutionAnomaly(
        **build_anomaly(
            pollutant_observations=[
                {"pollutant": "nox", "value": 21.0, "unit": "ppb"}
            ]
        )
    )

    assert anomaly.pollutant_observations[0].pollutant == "NOx"


def test_future_chemical_identifier_is_supported_and_provider_id_is_preserved():
    anomaly = AirPollutionAnomaly(
        **build_anomaly(
            pollutant_observations=[
                {
                    "pollutant": "C6H6",
                    "provider_pollutant_id": "benzene_hourly",
                    "value": 3.4,
                    "unit": "µg/m³",
                }
            ]
        )
    )

    observation = anomaly.pollutant_observations[0]
    assert observation.pollutant == "C6H6"
    assert observation.provider_pollutant_id == "benzene_hourly"


def test_missing_pollutant_observations_is_valid_incomplete_source_state():
    anomaly = AirPollutionAnomaly(**build_anomaly(pollutant_observations=[]))

    assert anomaly.pollutant_observations == []


def test_multiple_evidence_sources_are_preserved():
    sources = build_anomaly()["sources"] + [
        {
            "source_id": "regional-model",
            "source_name": "Regional atmospheric model",
            "source_type": "model_output",
            "retrieved_at": DETECTED_AT,
            "metadata": {"run": "2026-09-07T06:00:00Z"},
        }
    ]
    anomaly = AirPollutionAnomaly(**build_anomaly(sources=sources))

    assert {source.source_id for source in anomaly.sources} == {
        "station-17",
        "regional-model",
    }


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_confidence_boundaries_are_valid(confidence):
    assert AirPollutionAnomaly(**build_anomaly(confidence=confidence)).confidence == confidence


@pytest.mark.parametrize("confidence", [-0.01, 1.01, "0.8"])
def test_invalid_confidence_is_rejected(confidence):
    with pytest.raises(ValidationError):
        AirPollutionAnomaly(**build_anomaly(confidence=confidence))


@pytest.mark.parametrize(
    "location",
    [
        {"latitude": 90.1, "longitude": 34.8},
        {"latitude": -90.1, "longitude": 34.8},
        {"latitude": 32.1, "longitude": 180.1},
        {"latitude": 32.1, "longitude": -180.1},
    ],
)
def test_invalid_coordinates_are_rejected(location):
    with pytest.raises(ValidationError):
        AirPollutionAnomaly(**build_anomaly(location=location))


@pytest.mark.parametrize(
    "observation",
    [
        {"pollutant": "not a pollutant", "value": 5.0, "unit": "ppb"},
        {"pollutant": "wind", "value": 5.0, "unit": "ppb"},
        {"pollutant": "PM10", "value": -1.0, "unit": "µg/m³"},
        {"pollutant": "SO2", "value": 4.0, "unit": "percent"},
        {"pollutant": "CO", "value": "3.2", "unit": "ppm"},
    ],
)
def test_invalid_pollutant_value_type_or_unit_is_rejected(observation):
    with pytest.raises(ValidationError):
        AirPollutionAnomaly(**build_anomaly(pollutant_observations=[observation]))


def test_timezone_naive_timestamp_is_rejected():
    with pytest.raises(ValidationError):
        AirPollutionAnomaly(
            **build_anomaly(observed_at=datetime(2026, 9, 7, 8, 0))
        )


def test_detected_timestamp_cannot_precede_observation():
    with pytest.raises(ValidationError):
        AirPollutionAnomaly(
            **build_anomaly(detected_at=OBSERVED_AT - timedelta(seconds=1))
        )


def test_serialization_round_trip_preserves_contract():
    anomaly = AirPollutionAnomaly(**build_anomaly())
    restored = AirPollutionAnomaly.model_validate_json(anomaly.model_dump_json())

    assert restored == anomaly
    assert restored.observed_at.utcoffset() == timedelta(0)


def test_downstream_emergency_and_allocation_fields_are_not_required():
    anomaly = AirPollutionAnomaly(**build_anomaly())
    serialized = anomaly.model_dump(mode="json")

    forbidden_downstream_fields = {
        "emergency_required",
        "non_emergency",
        "human_life_risk_score",
        "evacuation",
        "dispatch",
        "allocated_resources",
        "response_actions",
    }
    assert forbidden_downstream_fields.isdisjoint(serialized)


def test_downstream_emergency_decisions_are_rejected_at_detector_boundary():
    with pytest.raises(ValidationError):
        AirPollutionAnomaly(
            **build_anomaly(),
            emergency_required=True,
        )
