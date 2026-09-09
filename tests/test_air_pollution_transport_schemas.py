"""EA-317 strict transport contracts; no provider or algorithm execution."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agents.air_pollution_transport_schemas import (
    PollutionTransportPredictionInput,
    PollutionTransportPredictionResult,
    SettlementTransportRelevanceResult,
)


ANOMALY_AT = datetime(2026, 9, 9, 9, 0, tzinfo=timezone.utc)
POINT = {"latitude": 32.1, "longitude": 34.8}


def anomaly_evidence():
    return {
        "detection_id": "air-pollution:test",
        "anomaly_observed_at": ANOMALY_AT,
        "pollutant_observations": [{
            "pollutant": "PM2.5",
            "concentration": 42.0,
            "normalized_unit": "µg/m³",
            "original_value": 42.0,
            "original_unit": "ug/m3",
            "evidence_reference_ids": ["pollution-reading"],
        }],
        "evidence_references": [{
            "evidence_id": "pollution-reading",
            "source_name": "Israel Ministry air monitoring",
            "source_type": "station_observation",
            "reference": "provider-station-1/channel-2",
        }],
    }


def ims_wind():
    return {
        "evidence_id": "wind-reading",
        "provider": "Israel Meteorological Service",
        "source_type": "station_observation",
        "provider_location_kind": "station",
        "provider_location_id": "ims-64",
        "provider_location_name": "Test station",
        "requested_coordinates": dict(POINT),
        "actual_provider_coordinates": {"latitude": 32.11, "longitude": 34.81},
        "raw_provider_timestamp": "2026-09-09T11:00:00+02:00",
        "wind_observed_at": ANOMALY_AT,
        "wind_aggregation_start": ANOMALY_AT - timedelta(minutes=10),
        "wind_aggregation_end": ANOMALY_AT,
        "retrieved_at": ANOMALY_AT + timedelta(minutes=1),
        "wind_from_direction_deg": 270.0,
        "wind_speed_mps": 4.0,
        "gust_from_direction_deg": 280.0,
        "gust_speed_mps": 7.0,
        "direction_stddev_deg": 12.0,
        "provider_validity": "valid",
        "provider_status": "1",
        "provider_channel_validity": {"WD": "valid", "WS": "valid", "STDwd": "valid"},
        "original_units": {
            "wind_direction": "deg",
            "wind_speed": "m/s",
            "gust_direction": "deg",
            "gust_speed": "m/s",
            "direction_stddev": "deg",
        },
        "time_offset_from_anomaly_seconds": 0.0,
        "reference": "https://api.ims.gov.il/v1/envista/stations/64",
    }


def open_meteo_wind(source_type="model_forecast"):
    valid_at = ANOMALY_AT + timedelta(hours=1)
    return {
        "evidence_id": "wind-model",
        "provider": "Open-Meteo",
        "source_type": source_type,
        "provider_location_kind": "model_grid",
        "provider_location_id": "32.125,34.750",
        "provider_location_name": "best_match grid cell",
        "requested_coordinates": dict(POINT),
        "actual_provider_coordinates": {"latitude": 32.125, "longitude": 34.75},
        "raw_provider_timestamp": "2026-09-09T10:00",
        "wind_valid_at": valid_at,
        "retrieved_at": ANOMALY_AT,
        "wind_from_direction_deg": 265.0,
        "wind_speed_mps": 3.5,
        "provider_validity": "unknown",
        "original_units": {"wind_direction": "°", "wind_speed": "km/h"},
        "time_offset_from_anomaly_seconds": 3600.0,
        "reference": "https://api.open-meteo.com/v1/forecast",
    }


def candidate(identifier="settlement-1", name="Test Town", latitude=32.1, longitude=34.9):
    return {
        "settlement_id": identifier,
        "name": name,
        "coordinates": {"latitude": latitude, "longitude": longitude},
        "source_provider": "OpenStreetMap",
        "source_feature_id": "node/123",
        "original_source_distance_m": 9500.0,
    }


def prediction_input(**changes):
    payload = {
        "prediction_id": "transport:test",
        "coordinator_routing_id": "route:test",
        "analysis_origin": {
            "analysis_origin_kind": "monitoring_location",
            "analysis_origin_coordinates": dict(POINT),
        },
        "anomaly_evidence": anomaly_evidence(),
        "wind_evidence": ims_wind(),
        "settlement_candidates": [candidate()],
    }
    payload.update(changes)
    return payload


def settlement_result(identifier="settlement-1", rank=1, **changes):
    payload = {
        "settlement_id": identifier,
        "name": "Test Town",
        "coordinates": {"latitude": 32.1, "longitude": 34.9},
        "geodesic_distance_m": 9500.0,
        "bearing_from_origin_deg": 90.0,
        "angular_difference_deg": 0.0,
        "along_wind_distance_m": 9500.0,
        "crosswind_distance_m": 0.0,
        "inside_transport_corridor": True,
        "relevance_score": 0.8,
        "score_components": {"alignment": 0.5, "distance": 0.3},
        "rank": rank,
        "potential_downwind_relevance": "higher",
    }
    payload.update(changes)
    return payload


def prediction_result(results=None, **changes):
    payload = {
        "prediction_id": "transport:test",
        "coordinator_routing_id": "route:test",
        "detection_id": "air-pollution:test",
        "analysis_origin": {
            "analysis_origin_kind": "monitoring_location",
            "analysis_origin_coordinates": dict(POINT),
        },
        "transport_screening": {
            "downwind_to_direction_deg": 90.0,
            "corridor_method": "direction_variability_screening",
            "corridor_half_angle_deg": 20.0,
            "algorithm_version": "transport-screening-v1",
            "parameter_version": "engineering-v1",
            "data_status": "success",
            "source_quality": "primary_observation",
            "generated_at": ANOMALY_AT + timedelta(minutes=2),
            "limitations": [
                "Monitoring location is not a confirmed pollution source; exposure is not confirmed."
            ],
            "evidence_reference_ids": ["wind-reading", "pollution-reading"],
        },
        "settlement_results": [settlement_result()] if results is None else results,
    }
    payload.update(changes)
    return payload


def test_valid_monitoring_location_input_roundtrips_and_normalizes_utc():
    payload = prediction_input()
    payload["anomaly_evidence"]["anomaly_observed_at"] = "2026-09-09T12:00:00+03:00"
    item = PollutionTransportPredictionInput.model_validate(payload)
    restored = PollutionTransportPredictionInput.model_validate_json(item.model_dump_json())
    assert restored == item
    assert item.analysis_origin.analysis_origin_kind == "monitoring_location"
    assert item.anomaly_evidence.anomaly_observed_at == ANOMALY_AT
    assert item.exposure_not_confirmed is True


def test_valid_correlated_source_input_requires_supporting_evidence():
    payload = prediction_input()
    payload["analysis_origin"] = {
        "analysis_origin_kind": "correlated_source",
        "analysis_origin_coordinates": POINT,
        "evidence_reference_ids": ["coordinator-correlation"],
    }
    item = PollutionTransportPredictionInput.model_validate(payload)
    assert item.analysis_origin.analysis_origin_kind == "correlated_source"
    payload["analysis_origin"]["evidence_reference_ids"] = []
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(payload)


def test_valid_confirmed_source_input_requires_and_preserves_evidence():
    payload = prediction_input()
    payload["analysis_origin"] = {
        "analysis_origin_kind": "confirmed_source",
        "analysis_origin_coordinates": dict(POINT),
        "evidence_reference_ids": ["confirmed-source-evidence"],
    }

    item = PollutionTransportPredictionInput.model_validate(payload)

    assert item.analysis_origin.analysis_origin_kind == "confirmed_source"
    assert item.analysis_origin.evidence_reference_ids == ["confirmed-source-evidence"]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("analysis_origin", "analysis_origin_kind"), "monitoring_station_source"),
        (("wind_evidence", "source_type"), "trajectory_model"),
        (("wind_evidence", "provider_validity"), "trusted"),
    ],
)
def test_unknown_contract_enum_values_are_rejected(path, value):
    payload = prediction_input()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(payload)


def test_ims_station_observation_preserves_gust_stdwd_and_channel_validity():
    wind = PollutionTransportPredictionInput.model_validate(prediction_input()).wind_evidence
    assert wind.source_type == "station_observation"
    assert wind.provider_location_kind == "station"
    assert wind.gust_from_direction_deg == 280.0
    assert wind.gust_speed_mps == 7.0
    assert wind.direction_stddev_deg == 12.0
    assert wind.provider_channel_validity["STDwd"] == "valid"


@pytest.mark.parametrize("source_type", ["model_forecast", "model_reanalysis"])
def test_open_meteo_model_evidence_uses_grid_and_valid_time(source_type):
    payload = prediction_input(wind_evidence=open_meteo_wind(source_type))
    wind = PollutionTransportPredictionInput.model_validate(payload).wind_evidence
    assert wind.provider_location_kind == "model_grid"
    assert wind.wind_valid_at is not None
    assert wind.wind_observed_at is None
    assert wind.actual_provider_coordinates != wind.requested_coordinates


def test_missing_optional_fields_are_valid():
    wind = ims_wind()
    for field in (
        "provider_location_name", "wind_aggregation_start", "wind_aggregation_end",
        "gust_from_direction_deg", "gust_speed_mps", "direction_stddev_deg",
        "provider_status", "reference",
    ):
        wind.pop(field, None)
    wind["original_units"] = {"wind_direction": "deg", "wind_speed": "m/s"}
    item = PollutionTransportPredictionInput.model_validate(prediction_input(wind_evidence=wind))
    assert item.wind_evidence.gust_speed_mps is None
    assert item.wind_evidence.direction_stddev_deg is None


def test_valid_per_settlement_output_and_multiple_results():
    second = settlement_result(
        "settlement-2", 2, name="Second Town",
        coordinates={"latitude": 32.12, "longitude": 34.95},
        angular_difference_deg=15.0, crosswind_distance_m=2400.0,
        relevance_score=0.55, potential_downwind_relevance="moderate",
    )
    item = PollutionTransportPredictionResult.model_validate(
        prediction_result(results=[settlement_result(), second])
    )
    assert [result.rank for result in item.settlement_results] == [1, 2]
    assert item.transport_screening.downwind_to_direction_deg == 90.0
    assert item.exposure_not_confirmed is True


def test_partial_result_roundtrips_with_complete_screening_metadata():
    payload = prediction_result()
    payload["transport_screening"]["data_status"] = "partial"

    item = PollutionTransportPredictionResult.model_validate(payload)
    restored = PollutionTransportPredictionResult.model_validate_json(
        item.model_dump_json()
    )

    assert restored == item
    assert restored.transport_screening.data_status == "partial"


def test_unavailable_result_rejects_derived_geometry_or_settlements():
    payload = prediction_result(results=[])
    payload["transport_screening"].update({
        "downwind_to_direction_deg": None,
        "corridor_method": None,
        "corridor_half_angle_deg": None,
        "data_status": "unavailable",
        "source_quality": "unavailable",
    })
    item = PollutionTransportPredictionResult.model_validate(payload)
    assert item.transport_screening.downwind_to_direction_deg is None
    assert item.settlement_results == []

    payload["settlement_results"] = [settlement_result()]
    with pytest.raises(ValidationError):
        PollutionTransportPredictionResult.model_validate(payload)


@pytest.mark.parametrize(
    "path,value",
    [
        (("analysis_origin", "analysis_origin_coordinates", "latitude"), 90.1),
        (("analysis_origin", "analysis_origin_coordinates", "longitude"), -180.1),
        (("wind_evidence", "actual_provider_coordinates", "latitude"), float("nan")),
        (("settlement_candidates", 0, "coordinates", "longitude"), float("inf")),
    ],
)
def test_invalid_coordinates_nan_and_infinity_are_rejected(path, value):
    payload = prediction_input()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(payload)


@pytest.mark.parametrize("value", [-0.1, 360.0, float("nan"), float("inf")])
def test_invalid_wind_direction_is_rejected(value):
    wind = ims_wind()
    wind["wind_from_direction_deg"] = value
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(prediction_input(wind_evidence=wind))


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf")])
def test_invalid_wind_speed_is_rejected(value):
    wind = ims_wind()
    wind["wind_speed_mps"] = value
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(prediction_input(wind_evidence=wind))


@pytest.mark.parametrize(
    "field",
    ["anomaly_observed_at"],
)
def test_naive_anomaly_timestamp_is_rejected(field):
    anomaly = anomaly_evidence()
    anomaly[field] = datetime(2026, 9, 9, 9, 0)
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(prediction_input(anomaly_evidence=anomaly))


@pytest.mark.parametrize("field", ["wind_observed_at", "retrieved_at", "wind_aggregation_start"])
def test_naive_wind_timestamps_are_rejected(field):
    wind = ims_wind()
    wind[field] = datetime(2026, 9, 9, 9, 0)
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(prediction_input(wind_evidence=wind))


def test_unknown_extra_fields_are_rejected_at_nested_boundary():
    payload = prediction_input()
    payload["wind_evidence"]["unexpected"] = True
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    [
        "response_plan", "allocation", "dispatch", "exposure_confirmed",
        "evacuation", "health_outcome",
    ],
)
def test_downstream_operational_fields_are_rejected(field):
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate({**prediction_input(), field: True})
    with pytest.raises(ValidationError):
        PollutionTransportPredictionResult.model_validate({**prediction_result(), field: True})


def test_relevance_score_is_not_a_probability_field():
    fields = SettlementTransportRelevanceResult.model_fields
    assert "relevance_score" in fields
    assert all("probability" not in name for name in fields)
    payload = settlement_result()
    payload["impact_probability"] = 0.8
    with pytest.raises(ValidationError):
        SettlementTransportRelevanceResult.model_validate(payload)


def test_kinematic_transport_estimate_is_nullable():
    without_estimate = SettlementTransportRelevanceResult.model_validate(settlement_result())
    assert without_estimate.kinematic_advection_time_seconds is None
    with_estimate = SettlementTransportRelevanceResult.model_validate(settlement_result(
        kinematic_advection_time_seconds=2375.0,
        transport_time_method="constant_wind_kinematic_screening",
        transport_time_assumptions=["Constant wind speed and direction over the screening path."],
    ))
    assert with_estimate.kinematic_advection_time_seconds == 2375.0


def test_incomplete_transport_time_metadata_is_rejected():
    with pytest.raises(ValidationError):
        SettlementTransportRelevanceResult.model_validate(settlement_result(
            kinematic_advection_time_seconds=2375.0,
        ))


def test_monitoring_location_cannot_claim_confirmed_source_or_exposure():
    payload = prediction_input()
    payload["analysis_origin"]["confirmed_source"] = True
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(payload)
    payload = prediction_input(exposure_not_confirmed=False)
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(payload)


def test_station_and_model_timestamp_semantics_cannot_be_mixed():
    wind = ims_wind()
    wind["wind_valid_at"] = ANOMALY_AT
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(prediction_input(wind_evidence=wind))
    wind = open_meteo_wind()
    wind["wind_observed_at"] = wind["wind_valid_at"]
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(prediction_input(wind_evidence=wind))


def test_timestamp_offset_and_requested_coordinate_must_match_context():
    payload = prediction_input()
    payload["wind_evidence"]["time_offset_from_anomaly_seconds"] = 1.0
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(payload)
    payload = prediction_input()
    payload["wind_evidence"]["requested_coordinates"] = {"latitude": 32.2, "longitude": 34.8}
    with pytest.raises(ValidationError):
        PollutionTransportPredictionInput.model_validate(payload)


def test_models_do_not_mutate_supplied_payloads():
    input_payload = prediction_input()
    result_payload = prediction_result()
    before_input, before_result = deepcopy(input_payload), deepcopy(result_payload)
    PollutionTransportPredictionInput.model_validate(input_payload)
    PollutionTransportPredictionResult.model_validate(result_payload)
    assert input_payload == before_input
    assert result_payload == before_result
