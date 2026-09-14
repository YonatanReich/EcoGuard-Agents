"""Focused offline tests for population screening composition."""

from unittest.mock import Mock

from agents.air_pollution_event_analyzer import AirPollutionNonEmergencyAnalyzer
from services.air_pollution_population_analysis import (
    AirPollutionPopulationAnalysisService,
)
from services.air_pollution_transport_spatial_output import (
    PollutionTransportSpatialOutput,
)
from test_air_pollution_non_emergency_analyzer import (
    GENERATED_AT,
    _analysis_input,
    _candidate,
    _transport_service,
)


def _spatial_output():
    transport, _ = _transport_service()
    return transport.predict(
        _candidate(), analysis_origin=_analysis_input().analysis_origin
    ).spatial_output


def _service(result=None, error=None):
    query = Mock()
    if error is not None:
        query.side_effect = error
    else:
        query.return_value = result or {
            "grid_available": True,
            "intersected_cell_count": 7,
            "weighted_population": 123.6,
        }
    return AirPollutionPopulationAnalysisService(query), query


def test_valid_corridor_preserves_area_weighted_population_and_settlements():
    service, query = _service()
    component = service.analyze(
        _spatial_output(),
        geometry_reference="transport:test:corridor",
        evidence_id="population-grid:test",
        queried_at=GENERATED_AT,
    )

    query.assert_called_once()
    assert query.call_args.args[0]["type"] == "Polygon"
    assert component.status == "partial"
    result = component.result
    assert result.assessment_kind == "geographically_relevant_population_screening"
    assert result.query_method == "area_weighted_population_grid_intersection"
    assert result.total_relevant_population == 124
    assert result.intersected_cell_count == 7
    assert result.relevant_settlements[0].name == "East Town"
    assert result.relevant_settlements[0].population is None
    assert result.relevant_settlements[0].population_status == "unavailable"
    assert result.population_is_affected_count is False
    assert result.exposure_not_confirmed is True
    assert result.dataset_id is None
    assert not {"affected_population", "exposed_population"} & set(
        type(result).model_fields
    )


def test_queryable_zero_is_distinct_from_unavailable_grid():
    zero_service, _ = _service(
        {
            "grid_available": True,
            "intersected_cell_count": 0,
            "weighted_population": 0.0,
        }
    )
    zero = zero_service.analyze(
        _spatial_output(),
        geometry_reference="transport:zero:corridor",
        evidence_id="population-grid:zero",
        queried_at=GENERATED_AT,
    )
    assert zero.status == "partial"
    assert zero.result.total_relevant_population == 0

    missing_service, _ = _service(
        {
            "grid_available": False,
            "intersected_cell_count": 0,
            "weighted_population": 0.0,
        }
    )
    missing = missing_service.analyze(
        _spatial_output(),
        geometry_reference="transport:missing:corridor",
        evidence_id="population-grid:missing",
        queried_at=GENERATED_AT,
    )
    assert missing.status == "unavailable"
    assert missing.result is None
    assert missing.unavailable_reason == "shared_population_grid_unavailable_or_unloaded"


def test_no_corridor_and_query_failure_are_explicitly_unavailable():
    spatial_payload = _spatial_output().model_dump(round_trip=True)
    spatial_payload.update(
        data_status="unavailable",
        centerline=None,
        corridor_polygon=None,
        downwind_to_direction_deg=None,
        settlements=[],
    )
    unavailable_spatial = PollutionTransportSpatialOutput.model_validate(
        spatial_payload
    )
    service, query = _service()
    no_corridor = service.analyze(
        unavailable_spatial,
        geometry_reference="transport:none:corridor",
        evidence_id="population-grid:none",
        queried_at=GENERATED_AT,
    )
    assert no_corridor.status == "unavailable"
    assert no_corridor.unavailable_reason == "transport_corridor_unavailable"
    query.assert_not_called()

    failed_service, _ = _service(error=RuntimeError("database detail"))
    failed = failed_service.analyze(
        _spatial_output(),
        geometry_reference="transport:failed:corridor",
        evidence_id="population-grid:failed",
        queried_at=GENERATED_AT,
    )
    assert failed.status == "unavailable"
    assert failed.unavailable_reason == "shared_population_query_failed"
    assert "database detail" not in failed.model_dump_json()


def test_analyzer_runs_population_only_after_transport_and_preserves_evidence():
    calls = []
    transport, wind = _transport_service()
    wind_result = wind.select_wind_evidence.return_value

    def select_wind(**kwargs):
        calls.append("transport")
        return wind_result

    wind.select_wind_evidence.side_effect = select_wind
    population, query = _service()

    def population_query(geometry):
        calls.append("population")
        return {
            "grid_available": True,
            "intersected_cell_count": 7,
            "weighted_population": 123.6,
        }

    query.side_effect = population_query
    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=transport,
        population_service=population,
        clock=lambda: GENERATED_AT,
    ).analyze(_analysis_input())

    assert calls == ["transport", "population"]
    assert report.population_impact.status == "partial"
    assert report.population_impact.result.total_relevant_population == 124
    assert report.population_impact.evidence[0].reference == "population_cells"
    assert all(
        limitation in report.limitations
        for limitation in report.population_impact.limitations
    )


def test_analyzer_does_not_query_population_without_transport_corridor():
    population, query = _service()
    report = AirPollutionNonEmergencyAnalyzer(
        transport_service=None,
        population_service=population,
        clock=lambda: GENERATED_AT,
    ).analyze(_analysis_input())

    query.assert_not_called()
    assert report.population_impact.status == "unavailable"
    assert report.population_impact.unavailable_reason == "transport_corridor_unavailable"
