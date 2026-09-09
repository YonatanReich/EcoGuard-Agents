"""EA-322 WGS84 spatial-output tests; no database or frontend integration."""

from math import isfinite

import pytest
from pydantic import ValidationError

from services.air_pollution_settlement_ranking import rank_settlement_candidates
from services.air_pollution_transport_corridor import (
    apply_transport_corridor,
    unavailable_transport_corridor,
)
from services.air_pollution_transport_geometry import geodesic_distance_m
from services.air_pollution_transport_spatial_output import (
    DatelineSpanningGeometryError,
    GeoJSONPolygon,
    PollutionTransportSpatialOutput,
    build_centerline,
    build_sector_polygon,
    destination_coordinate,
    prepare_transport_spatial_output,
)
from services.air_pollution_transport_time import (
    apply_transport_time_estimate,
    estimate_kinematic_transport_time,
)


ORIGIN = {"latitude": 0.0, "longitude": 0.0}
ONE_KM = 1_000.0


def candidate(identifier, latitude, longitude):
    return {
        "settlement_id": identifier,
        "name": identifier,
        "coordinates": {"latitude": latitude, "longitude": longitude},
    }


def corridor_result(*candidates, direction=90.0, half_angle=30.0, distance=200_000.0):
    ranked = rank_settlement_candidates(
        ORIGIN,
        (direction + 180.0) % 360.0,
        list(candidates),
    )
    return apply_transport_corridor(
        ranked,
        downwind_to_direction_deg=direction,
        corridor_half_angle_deg=half_angle,
        max_screening_distance_m=distance,
        corridor_method="fixed_angle_screening",
    )


@pytest.mark.parametrize(
    ("bearing", "latitude_sign", "longitude_sign"),
    [
        (0.0, 1, 0),
        (90.0, 0, 1),
        (180.0, -1, 0),
        (270.0, 0, -1),
    ],
)
def test_destination_coordinate_cardinal_directions(
    bearing,
    latitude_sign,
    longitude_sign,
):
    point = destination_coordinate(ORIGIN, bearing, ONE_KM)
    latitude = 0.0 if abs(point.latitude) < 1e-12 else point.latitude
    longitude = 0.0 if abs(point.longitude) < 1e-12 else point.longitude
    assert (-1 if latitude < 0 else 1 if latitude > 0 else 0) == latitude_sign
    assert (-1 if longitude < 0 else 1 if longitude > 0 else 0) == longitude_sign
    assert geodesic_distance_m(ORIGIN, point) == pytest.approx(ONE_KM, abs=1e-6)


def test_centerline_endpoint_is_at_maximum_distance():
    centerline = build_centerline(ORIGIN, 90.0, 50_000.0)
    longitude, latitude = centerline.coordinates[-1]
    assert geodesic_distance_m(
        ORIGIN,
        {"latitude": latitude, "longitude": longitude},
    ) == pytest.approx(50_000.0, abs=1e-6)


def test_spatial_output_preserves_downwind_direction():
    output = prepare_transport_spatial_output(
        ORIGIN,
        corridor_result(direction=90.0),
        arc_segment_count=4,
    )
    assert output.downwind_to_direction_deg == 90.0


def test_basic_sector_polygon_starts_and_ends_at_origin():
    polygon = build_sector_polygon(ORIGIN, 90.0, 30.0, 50_000.0, 6)
    ring = polygon.coordinates[0]
    assert ring[0] == (0.0, 0.0)
    assert ring[-1] == ring[0]
    assert len(ring) == 9


def test_polygon_model_rejects_unclosed_or_too_small_ring():
    with pytest.raises(ValidationError, match="closed"):
        GeoJSONPolygon(
            coordinates=[[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]]
        )
    with pytest.raises(ValidationError, match="at least four"):
        GeoJSONPolygon(coordinates=[[(0.0, 0.0), (1.0, 0.0), (0.0, 0.0)]])


def test_serialized_coordinates_use_longitude_latitude_order():
    result = prepare_transport_spatial_output(
        {"latitude": 32.1, "longitude": 34.8},
        corridor_result(),
        arc_segment_count=4,
    )
    serialized = result.model_dump(mode="json")
    assert serialized["origin"]["coordinates"] == [34.8, 32.1]


def test_sector_angular_boundaries_are_represented():
    polygon = build_sector_polygon(ORIGIN, 90.0, 30.0, 50_000.0, 6)
    first_outer = polygon.coordinates[0][1]
    last_outer = polygon.coordinates[0][-2]
    expected_first = destination_coordinate(ORIGIN, 60.0, 50_000.0)
    expected_last = destination_coordinate(ORIGIN, 120.0, 50_000.0)
    assert first_outer == pytest.approx((expected_first.longitude, expected_first.latitude))
    assert last_outer == pytest.approx((expected_last.longitude, expected_last.latitude))


def test_every_outer_arc_point_is_at_maximum_distance():
    polygon = build_sector_polygon(ORIGIN, 90.0, 30.0, 50_000.0, 12)
    for longitude, latitude in polygon.coordinates[0][1:-1]:
        assert geodesic_distance_m(
            ORIGIN,
            {"latitude": latitude, "longitude": longitude},
        ) == pytest.approx(50_000.0, abs=1e-6)


@pytest.mark.parametrize("segments", [1, 3, 18])
def test_arc_discretization_is_caller_configurable(segments):
    polygon = build_sector_polygon(ORIGIN, 90.0, 30.0, 50_000.0, segments)
    assert len(polygon.coordinates[0]) == segments + 3


@pytest.mark.parametrize("invalid", [0, -1, 1.5, float("nan"), float("inf")])
def test_invalid_arc_segment_count_is_rejected(invalid):
    with pytest.raises(ValidationError):
        build_sector_polygon(ORIGIN, 90.0, 30.0, 50_000.0, invalid)


@pytest.mark.parametrize(
    "invalid_origin",
    [
        {"latitude": 91.0, "longitude": 0.0},
        {"latitude": 0.0, "longitude": 181.0},
        {"latitude": float("nan"), "longitude": 0.0},
        {"latitude": 0.0, "longitude": float("inf")},
    ],
)
def test_invalid_destination_coordinates_are_rejected(invalid_origin):
    with pytest.raises(ValidationError):
        destination_coordinate(invalid_origin, 90.0, ONE_KM)


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_destination_distance_is_rejected(invalid):
    with pytest.raises(ValidationError):
        destination_coordinate(ORIGIN, 90.0, invalid)


@pytest.mark.parametrize("invalid", [0.0, -1.0, 180.0, float("nan"), float("inf")])
def test_invalid_sector_half_angle_is_rejected(invalid):
    with pytest.raises(ValidationError):
        build_sector_polygon(ORIGIN, 90.0, invalid, 50_000.0, 6)


@pytest.mark.parametrize("invalid", [-1.0, 360.0, float("nan"), float("inf")])
def test_invalid_destination_bearing_is_rejected(invalid):
    with pytest.raises(ValidationError):
        destination_coordinate(ORIGIN, invalid, ONE_KM)


def test_multiple_settlement_points_and_existing_values_are_preserved():
    corridor = corridor_result(
        candidate("inside", 0.0, 1.0),
        candidate("outside", 1.0, 1.0),
    )
    output = prepare_transport_spatial_output(ORIGIN, corridor, arc_segment_count=6)
    assert [item.settlement_id for item in output.settlements] == [
        item.settlement_id for item in corridor.settlement_results
    ]
    for spatial, existing in zip(output.settlements, corridor.settlement_results):
        assert spatial.point.coordinates == (
            existing.coordinates.longitude,
            existing.coordinates.latitude,
        )
        assert spatial.rank == existing.rank
        assert spatial.inside_transport_corridor == existing.inside_transport_corridor
        assert spatial.potential_downwind_relevance == existing.potential_downwind_relevance


def test_optional_transport_duration_is_preserved():
    corridor = corridor_result(candidate("inside", 0.0, 1.0))
    settlement = corridor.settlement_results[0]
    estimate = estimate_kinematic_transport_time(
        settlement.along_wind_distance_m,
        5.0,
        wind_evidence_suitability="usable",
    )
    corridor.settlement_results[0] = apply_transport_time_estimate(
        settlement,
        estimate,
    )
    output = prepare_transport_spatial_output(ORIGIN, corridor, arc_segment_count=6)
    spatial = output.settlements[0]
    assert spatial.kinematic_advection_time_seconds == estimate.kinematic_advection_time_seconds
    assert spatial.transport_time_method == "constant_wind_kinematic_screening"
    assert spatial.transport_time_assumptions == estimate.transport_time_assumptions


def test_spatial_output_has_no_exposure_or_impact_claim_fields():
    fields = set(PollutionTransportSpatialOutput.model_fields)
    forbidden = ("affected", "exposed", "impact_probability", "plume")
    assert not any(term in field for field in fields for term in forbidden)
    assert prepare_transport_spatial_output(
        ORIGIN,
        corridor_result(),
        arc_segment_count=4,
    ).exposure_not_confirmed


def test_repeated_spatial_output_is_deterministic():
    corridor = corridor_result(candidate("inside", 0.0, 1.0))
    outputs = [
        prepare_transport_spatial_output(
            ORIGIN,
            corridor,
            arc_segment_count=8,
        ).model_dump()
        for _ in range(10)
    ]
    assert all(output == outputs[0] for output in outputs[1:])


def test_postgis_mapping_and_metric_distance_semantics_are_explicit():
    metadata = prepare_transport_spatial_output(
        ORIGIN,
        corridor_result(),
        arc_segment_count=4,
    ).spatial_reference
    assert metadata.srid == 4326
    assert metadata.crs == "EPSG:4326"
    assert metadata.coordinate_order == "longitude_latitude"
    assert "ST_GeomFromGeoJSON" in metadata.geojson_to_geometry
    assert "ST_Intersects" in metadata.supported_future_predicates
    assert "ST_DWithin" in metadata.supported_future_predicates
    assert "ST_Distance" in metadata.supported_future_metric_functions
    assert "geography" in metadata.metric_distance_requirement
    assert "metre" in metadata.metric_distance_requirement


def test_dateline_spanning_sector_fails_clearly():
    with pytest.raises(DatelineSpanningGeometryError, match="dateline-spanning"):
        build_sector_polygon(
            {"latitude": 0.0, "longitude": 179.9},
            90.0,
            20.0,
            50_000.0,
            6,
        )


def test_destination_longitude_normalizes_across_dateline():
    point = destination_coordinate(
        {"latitude": 0.0, "longitude": 179.9},
        90.0,
        50_000.0,
    )
    assert -180.0 <= point.longitude <= 180.0
    assert point.longitude < 0.0
    assert isfinite(point.latitude)


def test_unavailable_corridor_outputs_origin_without_fabricated_geometry():
    corridor = unavailable_transport_corridor(
        corridor_half_angle_deg=20.0,
        max_screening_distance_m=50_000.0,
        corridor_method="fixed_angle_screening",
        limitation="Wind direction unavailable.",
    )
    output = prepare_transport_spatial_output(ORIGIN, corridor, arc_segment_count=4)
    assert output.data_status == "unavailable"
    assert output.centerline is None
    assert output.corridor_polygon is None
    assert output.settlements == []


def test_output_models_contain_no_database_frontend_or_runtime_fields():
    fields = set(PollutionTransportSpatialOutput.model_fields)
    for forbidden in ["database", "connection", "orm", "frontend", "runtime"]:
        assert forbidden not in fields
