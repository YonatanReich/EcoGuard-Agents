"""Runtime bridge tests for provider-backed pollution transport screening."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

import services.air_pollution_transport_prediction_service as prediction_module
from agents.air_pollution_anomaly_schemas import AirPollutionAnomaly
from agents.air_pollution_correlation import correlation_candidate
from agents.air_pollution_spatial_schemas import (
    PollutionSpatialContext,
    SpatiallyEnrichedAirPollutionAnomaly,
)
from agents.air_pollution_transport_schemas import WindEvidence
from services.air_pollution_transport_prediction_service import (
    TRANSPORT_ARC_SEGMENTS_ENV,
    TRANSPORT_ENABLED_ENV,
    TRANSPORT_HALF_ANGLE_ENV,
    TRANSPORT_MAX_DISTANCE_ENV,
    TRANSPORT_MIN_WIND_SPEED_ENV,
    WIND_MAX_AGE_MINUTES_ENV,
    AirPollutionTransportConfiguration,
    AirPollutionTransportConfigurationError,
    AirPollutionTransportPredictionService,
    configured_air_pollution_transport_prediction_service,
    load_air_pollution_transport_configuration,
)


NOW = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
ORIGIN = {"latitude": 32.0853, "longitude": 34.7818}
UNIT = "\u00b5g/m\u00b3"


def anomaly(identifier: str = "pollution-transport-1") -> AirPollutionAnomaly:
    return AirPollutionAnomaly(
        detection_id=identifier,
        observed_at=NOW,
        detected_at=NOW,
        location=ORIGIN,
        pollutant_observations=[
            {
                "pollutant": "PM2.5",
                "value": 42.0,
                "unit": UNIT,
                "provider_unit": "ug/m3",
                "observed_at": NOW,
                "source_id": "ministry",
            }
        ],
        severity="medium",
        confidence=0.7,
        explanation="Real monitoring-location anomaly.",
        sources=[
            {
                "source_id": "ministry",
                "source_name": "Israeli Ministry monitoring network",
                "metadata": {"station_id": "air-1", "channel_id": "pm25-1"},
            }
        ],
    )


def candidate(*, settlements: bool = True):
    event = anomaly()
    if not settlements:
        return correlation_candidate(event)
    context = PollutionSpatialContext(
        location=event.location,
        lookup_radius_km=2.0,
        status="success",
        source="OpenStreetMap via existing geospatial agent",
        collected_at=NOW,
        nearby_settlements=[
            {
                "name": "Southeast settlement",
                "osm_id": 100,
                "osm_type": "node",
                "latitude": 32.075,
                "longitude": 34.795,
                "distance_km": 1.7,
            },
            {
                "name": "Northwest settlement",
                "osm_id": 200,
                "osm_type": "node",
                "latitude": 32.095,
                "longitude": 34.77,
                "distance_km": 1.5,
            },
        ],
        limitations=["Two-kilometre proximity lookup is not an exposure zone."],
    )
    return correlation_candidate(
        SpatiallyEnrichedAirPollutionAnomaly(
            anomaly=event,
            spatial_context=context,
        )
    )


def wind_evidence(**changes) -> WindEvidence:
    payload = {
        "evidence_id": "ims-wind:test-station:2026-09-09T10:00:00+00:00",
        "provider": "IMS",
        "source_type": "station_observation",
        "provider_location_kind": "station",
        "provider_location_id": "test-station",
        "provider_location_name": "Test IMS station",
        "requested_coordinates": ORIGIN,
        "actual_provider_coordinates": {"latitude": 32.1, "longitude": 34.78},
        "raw_provider_timestamp": "2026-09-09T12:00:00+03:00",
        "wind_observed_at": NOW,
        "wind_aggregation_start": datetime(2026, 9, 9, 9, 50, tzinfo=timezone.utc),
        "wind_aggregation_end": NOW,
        "retrieved_at": NOW,
        "wind_from_direction_deg": 307.0,
        "wind_speed_mps": 4.0,
        "direction_stddev_deg": 11.0,
        "gust_from_direction_deg": 300.0,
        "gust_speed_mps": 6.0,
        "provider_validity": "valid",
        "provider_status": "WD=1; WS=1",
        "provider_channel_validity": {"WD": "valid", "WS": "valid"},
        "original_units": {
            "wind_direction": "deg",
            "wind_speed": "m/sec",
            "direction_stddev": "deg",
            "gust_direction": "deg",
            "gust_speed": "m/sec",
        },
        "time_offset_from_anomaly_seconds": 0.0,
        "reference": "https://api.ims.gov.il/v1/envista/stations/999/data",
        "metadata": {"station_distance_m": 1234.0},
    }
    payload.update(changes)
    return WindEvidence.model_validate(payload)


class FakeWindEvidenceProvider:
    def __init__(self, evidence: WindEvidence | None = None, error: Exception | None = None):
        self.evidence = evidence or wind_evidence()
        self.error = error
        self.calls = []

    def select_wind_evidence(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return type("Selection", (), {"wind_evidence": self.evidence})()


def configuration(**changes) -> AirPollutionTransportConfiguration:
    payload = {
        "corridor_half_angle_deg": 30.0,
        "max_screening_distance_m": 20_000.0,
        "arc_segment_count": 8,
        "wind_max_age_minutes": 60.0,
        "minimum_wind_speed_mps": None,
    }
    payload.update(changes)
    return AirPollutionTransportConfiguration(**payload)


def service(**config_changes):
    provider = FakeWindEvidenceProvider()
    return (
        AirPollutionTransportPredictionService(
            wind_evidence_service=provider,
            configuration=configuration(**config_changes),
        ),
        provider,
    )


def test_actual_ea318_to_ea322_pipeline_builds_real_screening_output():
    predictor, provider = service()

    result = predictor.predict(candidate())

    assert len(provider.calls) == 1
    assert provider.calls[0]["analysis_coordinates"].model_dump() == ORIGIN
    assert provider.calls[0]["anomaly_observed_at"] == NOW
    assert provider.calls[0]["maximum_observation_age_seconds"] == 3600.0
    assert result.analysis_origin.analysis_origin_kind == "monitoring_location"
    assert result.spatial_output.downwind_to_direction_deg == 127.0
    assert result.spatial_output.origin.coordinates == (34.7818, 32.0853)
    assert result.spatial_output.corridor_method == "fixed_angle_screening"
    assert result.spatial_output.corridor_half_angle_deg == 30.0
    assert result.spatial_output.max_screening_distance_m == 20_000.0
    assert result.spatial_output.arc_segment_count == 8
    assert result.spatial_output.direction_stddev_deg == 11.0
    assert result.exposure_not_confirmed is True


def test_real_settlements_are_ranked_corridor_screened_and_timed():
    predictor, _ = service()

    result = predictor.predict(candidate()).spatial_output
    settlements = {item.name: item for item in result.settlements}

    southeast = settlements["Southeast settlement"]
    northwest = settlements["Northwest settlement"]
    assert southeast.rank == 1
    assert southeast.inside_transport_corridor is True
    assert southeast.relevance_score <= 1.0
    assert southeast.kinematic_advection_time_seconds is not None
    assert southeast.transport_time_method == "constant_wind_kinematic_screening"
    assert northwest.inside_transport_corridor is False
    assert northwest.kinematic_advection_time_seconds is None


def test_existing_ea318_through_ea322_functions_are_composed_not_reimplemented(monkeypatch):
    names = [
        "downwind_to_direction_deg",
        "rank_settlement_candidates",
        "apply_transport_corridor",
        "estimate_corridor_settlement_transport_time",
        "prepare_transport_spatial_output",
    ]
    calls = {name: 0 for name in names}
    for name in names:
        original = getattr(prediction_module, name)

        def wrapper(*args, _name=name, _original=original, **kwargs):
            calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(prediction_module, name, wrapper)

    predictor, _ = service()
    predictor.predict(candidate())

    assert all(count >= 1 for count in calls.values())


def test_empty_settlement_context_still_builds_centerline_and_corridor():
    predictor, _ = service()

    output = predictor.predict(candidate(settlements=False)).spatial_output

    assert output.data_status == "success"
    assert output.centerline is not None
    assert output.corridor_polygon is not None
    assert output.settlements == []


def test_explicit_minimum_wind_speed_suppresses_duration_without_removing_geometry():
    predictor, _ = service(minimum_wind_speed_mps=5.0)

    output = predictor.predict(candidate()).spatial_output

    assert output.centerline is not None
    assert all(
        item.kinematic_advection_time_seconds is None
        for item in output.settlements
    )


def test_stdwd_is_preserved_but_does_not_select_configured_half_angle():
    predictor, _ = service(corridor_half_angle_deg=22.0)

    output = predictor.predict(candidate()).spatial_output

    assert output.direction_stddev_deg == 11.0
    assert output.corridor_half_angle_deg == 22.0


def test_monitoring_location_limitations_and_safe_semantics_are_structural():
    predictor, _ = service()
    result = predictor.predict(candidate())
    serialized = result.model_dump(mode="json")
    limitations = " ".join(result.spatial_output.limitations).lower()

    assert result.analysis_origin.analysis_origin_kind == "monitoring_location"
    assert result.spatial_output.exposure_not_confirmed is True
    assert "monitoring location" in limitations
    assert "not a confirmed emission source" in limitations
    forbidden = {"arrival_time", "pollution_eta", "affected", "exposed"}
    assert not forbidden & serialized.keys()
    assert "probability" not in inspect.getsource(
        AirPollutionTransportPredictionService.predict
    ).lower()


def test_mismatched_wind_origin_is_rejected():
    predictor, _ = service()
    mismatched = wind_evidence(
        requested_coordinates={"latitude": 31.0, "longitude": 35.0}
    )

    with pytest.raises(ValueError, match="coordinates"):
        predictor.predict(candidate(), wind_evidence=mismatched)


def _set_enabled_environment(monkeypatch):
    monkeypatch.setenv(TRANSPORT_ENABLED_ENV, "true")
    monkeypatch.setenv(TRANSPORT_HALF_ANGLE_ENV, "30")
    monkeypatch.setenv(TRANSPORT_MAX_DISTANCE_ENV, "20000")
    monkeypatch.setenv(TRANSPORT_ARC_SEGMENTS_ENV, "8")
    monkeypatch.setenv(WIND_MAX_AGE_MINUTES_ENV, "60")
    monkeypatch.delenv(TRANSPORT_MIN_WIND_SPEED_ENV, raising=False)


def test_disabled_configuration_requires_no_scientific_parameters(monkeypatch):
    monkeypatch.setenv(TRANSPORT_ENABLED_ENV, "false")
    for name in (
        TRANSPORT_HALF_ANGLE_ENV,
        TRANSPORT_MAX_DISTANCE_ENV,
        TRANSPORT_ARC_SEGMENTS_ENV,
        WIND_MAX_AGE_MINUTES_ENV,
    ):
        monkeypatch.delenv(name, raising=False)

    assert load_air_pollution_transport_configuration() is None


def test_disabled_factory_does_not_construct_ims_client(monkeypatch):
    monkeypatch.setenv(TRANSPORT_ENABLED_ENV, "false")

    def unexpected_client_construction():
        raise AssertionError("disabled screening must not construct an IMS client")

    monkeypatch.setattr(
        prediction_module,
        "IMSWindObservationClient",
        unexpected_client_construction,
    )

    assert configured_air_pollution_transport_prediction_service() is None


def test_enabled_configuration_requires_every_explicit_parameter(monkeypatch):
    _set_enabled_environment(monkeypatch)
    monkeypatch.delenv(TRANSPORT_HALF_ANGLE_ENV)

    with pytest.raises(
        AirPollutionTransportConfigurationError,
        match="required_configuration_missing",
    ):
        load_air_pollution_transport_configuration()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (TRANSPORT_HALF_ANGLE_ENV, "180"),
        (TRANSPORT_MAX_DISTANCE_ENV, "0"),
        (TRANSPORT_ARC_SEGMENTS_ENV, "1.5"),
        (WIND_MAX_AGE_MINUTES_ENV, "nan"),
        (TRANSPORT_MIN_WIND_SPEED_ENV, "0"),
    ],
)
def test_invalid_explicit_configuration_is_safely_rejected(monkeypatch, name, value):
    _set_enabled_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(
        AirPollutionTransportConfigurationError,
        match="configuration_invalid",
    ):
        load_air_pollution_transport_configuration()


def test_valid_environment_configuration_preserves_exact_values(monkeypatch):
    _set_enabled_environment(monkeypatch)
    monkeypatch.setenv(TRANSPORT_MIN_WIND_SPEED_ENV, "1.25")

    loaded = load_air_pollution_transport_configuration()

    assert loaded == AirPollutionTransportConfiguration(
        corridor_half_angle_deg=30.0,
        max_screening_distance_m=20_000.0,
        arc_segment_count=8,
        wind_max_age_minutes=60.0,
        minimum_wind_speed_mps=1.25,
    )
