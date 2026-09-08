"""EA-310 uses real agent normalization shapes and mocked transport only."""

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from agents.air_pollution_anomaly_schemas import AirPollutionAnomaly
from agents.air_pollution_spatial_enrichment import AirPollutionSpatialEnricher, LAYERS
from agents.air_pollution_spatial_schemas import SpatiallyEnrichedAirPollutionAnomaly
from agents.geospatial_context_agent import GeospatialContextAgent

POINT = {"latitude": 32.1, "longitude": 34.8}


@pytest.fixture
def anomaly():
    return AirPollutionAnomaly(
        detection_id="test-detection", observed_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        detected_at=datetime(2026, 9, 8, tzinfo=timezone.utc), location=POINT,
        severity="medium", confidence=0.65, explanation="Injected anomaly for enrichment test",
        sources=[{"source_id": "station-1", "source_name": "Test observation source"}],
    )


def envelope():
    return {
        "metadata": {"data_source": "OpenStreetMap / Overpass API", "collection_status": "success",
                     "timestamp": "2026-09-08T12:00:00+02:00"},
        "location": {**POINT, "radius_km": 2.0},
        "geospatial_context": {layer: [] for layer in LAYERS}, "missing_layers": [],
    }


def test_real_normalization_single_lookup_preserves_features(anomaly):
    agent = GeospatialContextAgent()
    elements = [
        {"id": 1, "type": "node", "lat": 32.1, "lon": 34.8,
         "tags": {"place": "town", "name": "Test town", "population": "1200"}},
        {"id": 2, "type": "way", "center": {"lat": 32.11, "lon": 34.81},
         "tags": {"highway": "primary", "name": "Test road", "ref": "4"}},
    ]
    for index, amenity in enumerate(["hospital", "hospital", "police", "police", "fire_station", "fire_station"], 10):
        elements.append({"id": index, "type": "node", "lat": 32.11, "lon": 34.81,
                         "tags": {"amenity": amenity, "name": f"Test facility {index}"}})
    agent.execute_overpass_query = Mock(return_value=elements)
    before = anomaly.model_dump()
    result = AirPollutionSpatialEnricher(agent).enrich(anomaly)
    agent.execute_overpass_query.assert_called_once()
    context = result.spatial_context
    assert context.location.model_dump() == POINT
    assert context.lookup_radius_km == 2
    assert context.source == agent.source_name
    assert context.collected_at.utcoffset().total_seconds() == 0
    assert context.nearby_settlements[0].osm_id == 1
    assert context.nearby_settlements[0].population == "1200"
    assert context.nearby_roads[0].ref == "4"
    assert context.nearby_roads[0].latitude == 32.11
    assert context.nearby_roads[0].osm_id is None  # Agent does not preserve road IDs.
    for layer in ("nearby_hospitals", "nearby_police_stations", "nearby_fire_stations"):
        assert len(getattr(context, layer)) == 2
        assert all(item.distance_km is None for item in getattr(context, layer))
    assert context.status == "partial"  # Agent marks its unsupported empty layers missing.
    assert "nearby_green_areas" in context.missing_layers
    assert anomaly.model_dump() == result.anomaly.model_dump() == before


def test_existing_context_avoids_network_and_roundtrips(anomaly):
    provider = Mock()
    supplied = envelope()
    supplied["geospatial_context"]["nearby_hospitals"] = [
        {"name": "Test hospital", **POINT, "distance_km": 0.7, "osm_id": 8, "osm_type": "way"},
    ]
    before = deepcopy(supplied)
    result = AirPollutionSpatialEnricher(provider).enrich(anomaly, geospatial_context=supplied)
    provider.fetch_nearby_context.assert_not_called()
    assert supplied == before
    assert result.spatial_context.status == "success"
    assert result.spatial_context.nearby_hospitals[0].distance_km == 0.7
    assert result.spatial_context.collected_at.hour == 10
    assert SpatiallyEnrichedAirPollutionAnomaly.model_validate_json(result.model_dump_json()) == result


def test_empty_results_are_valid_without_fabrication(anomaly):
    result = AirPollutionSpatialEnricher(Mock()).enrich(anomaly, geospatial_context=envelope())
    assert result.spatial_context.status == "success"
    assert all(getattr(result.spatial_context, layer) == [] for layer in LAYERS)


@pytest.mark.parametrize("mode", ["exception", "failed", "malformed"])
def test_failure_preserves_anomaly_and_sanitizes_errors(anomaly, mode):
    provider = Mock()
    if mode == "exception":
        provider.fetch_nearby_context.side_effect = RuntimeError("secret-request-url")
    elif mode == "failed":
        response = envelope()
        response["metadata"]["collection_status"] = "failed"
        response["error"] = "secret-request-url"
        provider.fetch_nearby_context.return_value = response
    else:
        provider.fetch_nearby_context.return_value = []
    result = AirPollutionSpatialEnricher(provider).enrich(anomaly)
    assert result.anomaly == anomaly
    assert result.spatial_context.status == "unavailable"
    assert "secret-request-url" not in result.model_dump_json()


def test_malformed_feature_does_not_discard_valid_neighbors(anomaly):
    response = envelope()
    response["geospatial_context"]["nearby_roads"] = [
        {"name": "No center provided", "latitude": None, "longitude": None},
        {"name": "Valid zero", "latitude": 0.0, "longitude": 0.0},
        {"name": "Bad", "latitude": 91.0, "longitude": 34.8},
        {"name": "Half coordinate", "latitude": 32.1},
        {"name": "NaN", "latitude": float("nan"), "longitude": 34.8},
    ]
    context = AirPollutionSpatialEnricher(Mock()).enrich(anomaly, geospatial_context=response).spatial_context
    assert len(context.nearby_roads) == 2
    assert context.excluded_feature_counts == {"nearby_roads": 3}
    assert context.status == "partial"


@pytest.mark.parametrize("change", ["location", "radius", "timestamp", "layer", "metadata"])
def test_partial_or_mismatched_response(anomaly, change):
    response = envelope()
    if change == "location":
        response["location"]["latitude"] = 33.0
    elif change == "radius":
        response["location"]["radius_km"] = 5.0
    elif change == "timestamp":
        response["metadata"]["timestamp"] = "not-a-time"
    elif change == "layer":
        response["geospatial_context"].pop("nearby_roads")
    else:
        response.pop("metadata")
    context = AirPollutionSpatialEnricher(Mock()).enrich(anomaly, geospatial_context=response).spatial_context
    assert context.status == ("unavailable" if change in {"location", "radius"} else "partial")
    assert context.errors


@pytest.mark.parametrize("radius", [0, -1, float("nan"), True, "2"])
def test_invalid_radius_rejected_before_network(anomaly, radius):
    provider = Mock()
    with pytest.raises(ValidationError):
        AirPollutionSpatialEnricher(provider).enrich(anomaly, radius_km=radius)
    provider.fetch_nearby_context.assert_not_called()


def test_invalid_anomaly_coordinate_rejected_before_network(anomaly):
    provider = Mock()
    invalid = anomaly.model_copy(update={"location": anomaly.location.model_copy(update={"latitude": 100.0})})
    with pytest.raises(ValidationError):
        AirPollutionSpatialEnricher(provider).enrich(invalid)
    provider.fetch_nearby_context.assert_not_called()


def test_no_operational_fields_promoted(anomaly):
    response = envelope()
    response["geospatial_context"]["nearby_hospitals"] = [{
        "name": "Test hospital", **POINT, "dispatched": True, "available": True,
        "response_actions": ["invented"], "emergency_required": True,
    }]
    result = AirPollutionSpatialEnricher(Mock()).enrich(anomaly, geospatial_context=response)
    feature = result.spatial_context.nearby_hospitals[0].model_dump()
    assert not {"dispatched", "available", "response_actions", "emergency_required"} & feature.keys()
    assert result.anomaly.model_dump() == anomaly.model_dump()
    with pytest.raises(ValidationError):
        SpatiallyEnrichedAirPollutionAnomaly(**result.model_dump(), dispatch=True)
