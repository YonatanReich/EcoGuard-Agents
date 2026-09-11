import copy
import json
from unittest.mock import Mock
import pytest
from agents.resource_allocation_agent import ResourceAllocationAgent

LOCATION = {"latitude": 31, "longitude": 35}

def facility(name, lat):
    return {"name": name, "latitude": lat, "longitude": 35}

def run(search, units=None, level="low", context=None):
    agent = ResourceAllocationAgent(geospatial_agent=search)
    return agent.allocate_resources(LOCATION, context or {}, {"recommended_units": units or ["fire_department"], "responding_to": {"risk_level": level}})

@pytest.mark.parametrize("level", ["low", "medium", "high", "critical"])
def test_all_in_radius_preserves_source_fields_without_mutation(level):
    records = [facility("a",31.001), facility("b",31.002), facility("far",31.3), {"name":"invalid"}]
    records[0]["available"] = False
    records[0]["availability"] = "unknown"
    original = copy.deepcopy(records)
    search = Mock()
    search.fetch_facilities.return_value = {"status":"success", "facilities":records + records[:1]}
    result = run(search, level=level)
    selected = result["allocated_units"]["fire_stations"]
    expected = ["a", "b"] if level in ("high", "critical") else ["a"]
    assert [r["name"] for r in selected] == expected
    assert selected[0]["available"] is False
    assert selected[0]["availability"] == "unknown"
    assert records == original
    assert result["status"] == "success"
    assert search.fetch_facilities.call_count == 1
    json.dumps(result, allow_nan=False)

def test_fallback_selects_one_nearest_and_only_missing_type():
    search = Mock()
    search.fetch_facilities.side_effect = [
        {"status":"success", "facilities":[facility("fire",31.001)]},
        {"status":"success", "facilities":[]},
        {"status":"success", "facilities":[facility("far",31.2),facility("near",31.1)]}]
    result = run(search,["fire_department","police"])
    assert result["allocated_units"]["police_stations"][0]["name"] == "near"
    assert len(result["allocated_units"]["police_stations"]) == 1
    assert [c.args[2:] for c in search.fetch_facilities.call_args_list] == [("fire_station",5),("police_station",5),("police_station",30)]


def test_response_plan_does_not_require_resource_quantities():
    search = Mock()
    search.fetch_facilities.side_effect = [
        {"status": "success", "facilities": [facility("fire", 31.001)]},
        {"status": "success", "facilities": [facility("police", 31.002)]},
    ]
    agent = ResourceAllocationAgent(geospatial_agent=search)

    result = agent.allocate_resources(LOCATION, {}, {
        "required_resources": None,
        "recommended_units": ["fire_department", "police"],
        "responding_to": {"risk_score": 78, "risk_level": "high"},
    })

    assert result["status"] == "success"
    assert result["allocated_units"]["fire_stations"][0]["name"] == "fire"
    assert result["allocated_units"]["police_stations"][0]["name"] == "police"
    assert search.fetch_facilities.call_count == 2


def test_allocated_units_contains_only_requested_types_and_never_roads():
    search = Mock()
    search.fetch_facilities.return_value = {
        "status": "success",
        "facilities": [facility("hospital", 31.001)],
    }
    agent = ResourceAllocationAgent(geospatial_agent=search)

    roads = [{"name": "Route 4", "ref": "4"}]
    result = agent.allocate_resources(LOCATION, {"nearby_roads": roads}, {
        "recommended_units": ["medical_services"],
        "responding_to": {"risk_level": "medium"},
    })

    assert set(result["allocated_units"]) == {"hospitals"}
    assert result["allocated_units"]["hospitals"][0]["name"] == "hospital"
    assert result["nearby_roads"] == roads
    assert "roads" not in result["allocated_units"]


@pytest.mark.parametrize("response_plan", [
    {"recommended_units": [], "responding_to": {"risk_level": "low"}},
    {"responding_to": {"risk_level": "low"}},
])
def test_no_recommended_units_means_no_allocation_needed(response_plan):
    search = Mock()
    agent = ResourceAllocationAgent(geospatial_agent=search)

    result = agent.allocate_resources(LOCATION, {}, response_plan)

    assert result["status"] == "success"
    assert result["allocation_needed"] is False
    assert result["reason"] == "no_resources_required"
    assert result["allocated_units"] == {}
    assert result["shortages"] == {}
    assert result["errors"] == []
    search.fetch_facilities.assert_not_called()

def test_max_radius_and_no_results():
    search = Mock()
    search.fetch_facilities.return_value = {"status":"success", "facilities":[]}
    result = run(search)
    assert result["shortages"] == {"fire_station":1}
    assert result["status"] == "partial"
    assert [call.args[3] for call in search.fetch_facilities.call_args_list] == [5,30,50]

def test_failure_preserves_existing_candidates_and_stops():
    search = Mock()
    search.fetch_facilities.side_effect = TimeoutError()
    result = run(search,context={"nearby_fire_stations":[facility("known",31.001)]})
    assert result["status"] == "partial"
    assert result["allocated_units"]["fire_stations"][0]["name"] == "known"
    assert result["errors"] and result["shortages"] == {}
    assert search.fetch_facilities.call_count == 1

def test_risk_radius_and_unsupported_units():
    search = Mock()
    search.fetch_facilities.return_value = {"status":"success", "facilities":[facility("a",31.02)]}
    result = run(search,["medical_services","aerial_firefighting"],level="high")
    assert result["alert_radius_km"] == 15
    assert result["allocated_units"]["hospitals"]
    assert result["unsupported_units"] == ["aerial_firefighting"]
    assert result["status"] == "partial"

def test_missing_risk_does_not_search():
    search = Mock()
    result = run(search,level=None)
    assert result["reason"] == "risk_level_unavailable"
    search.fetch_facilities.assert_not_called()

@pytest.mark.parametrize("lat", [float("nan"), float("inf"), 91, True])
def test_invalid_coordinates(lat):
    with pytest.raises(ValueError):
        ResourceAllocationAgent._coordinates({"latitude":lat,"longitude":35})

def test_layer_lookup_uses_only_requested_type():
    from agents.geospatial_context_agent import GeospatialContextAgent
    geo = GeospatialContextAgent()
    geo.execute_overpass_query = Mock(return_value=[])
    result = geo.fetch_facilities(31,35,"police_station",10)
    query = geo.execute_overpass_query.call_args.args[0]
    assert '"amenity"="police"' in query
    assert '"amenity"="hospital"' not in query
    assert result == {"status":"success","facilities":[]}


@pytest.mark.parametrize("level,expected", [
    ("low", ["near"]), ("medium", ["near"]),
    ("high", ["near", "far"]), ("critical", ["near", "far"]),
])
@pytest.mark.parametrize("empty_expansions", [0, 1])
def test_expanded_selection_depends_on_risk(level, expected, empty_expansions):
    search = Mock()
    radius = 30 if empty_expansions == 0 else 50
    near_lat = 31.2 if radius == 30 else 31.3
    far_lat = 31.25 if radius == 30 else 31.4
    search.fetch_facilities.side_effect = [
        {"status": "success", "facilities": []}
        for _ in range(1 + empty_expansions)
    ] + [{"status": "success", "facilities": [
        facility("far", far_lat), facility("outside", 31.6),
        facility("near", near_lat), facility("near", near_lat),
    ]}]
    result = run(search, level=level)
    selected = result["allocated_units"]["fire_stations"]
    assert [f["name"] for f in selected] == expected
    assert result["status"] == "success"
    assert search.fetch_facilities.call_count == 2 + empty_expansions
    assert all(f["distance_km"] <= radius for f in selected)
    reason = "within_expanded_radius" if level in ("high", "critical") else "nearest_found_in_expanded_search"
    assert all(f["selection_reason"] == reason for f in selected)


@pytest.mark.parametrize("body,kind,list_name", [
    ("fire_department", "fire_station", "fire_stations"),
    ("police", "police_station", "police_stations"),
    ("medical_services", "hospital", "hospitals"),
])
def test_mapping_matches_real_geospatial_response(body, kind, list_name):
    from agents.geospatial_context_agent import GeospatialContextAgent
    geo = GeospatialContextAgent()
    amenity = {"fire_station": "fire_station", "police_station": "police", "hospital": "hospital"}[kind]
    geo.execute_overpass_query = Mock(return_value=[{
        "type": "node", "id": 1, "lat": 31.001, "lon": 35,
        "tags": {"amenity": amenity, "name": "Test facility"},
    }])
    agent = ResourceAllocationAgent(geospatial_agent=geo)
    result = agent.allocate_resources(LOCATION, {}, {
        "recommended_units": [body, body], "responding_to": {"risk_level": "low"}})
    assert result["status"] == "success"
    assert result["allocated_units"][list_name][0]["unit_type"] == kind
    assert result["allocated_units"][list_name][0]["name"] == "Test facility"
    assert geo.execute_overpass_query.call_count == 1
