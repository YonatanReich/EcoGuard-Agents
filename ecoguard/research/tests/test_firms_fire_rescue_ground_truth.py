from research.datasets.build_firms_fire_rescue_ground_truth import (
    SettlementSpatialIndex,
    build_official_index,
    match_candidates,
    normalize_lamas_code,
    settlement_polygons,
    validate_boundary_geojson,
)


def square(west, south, east, north):
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]
        ],
    }


def boundary_collection():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "Muni_Heb": "עיר א",
                    "CR_LAMAS": "123",
                    "Vaad_Heb": None,
                    "CV_LAMAS": None,
                    "AreaSQM": 100,
                },
                "geometry": square(34.8, 31.8, 35.0, 32.0),
            },
            {
                "type": "Feature",
                "properties": {
                    "Muni_Heb": "מועצה אזורית",
                    "CR_LAMAS": "9000",
                    "Vaad_Heb": "יישוב ב",
                    "CV_LAMAS": "456",
                    "AreaSQM": 10,
                },
                "geometry": square(35.1, 31.8, 35.2, 31.9),
            },
        ],
    }


def candidate(identifier="candidate-1", timestamp="2024-06-15T10:00:00Z", lat=31.9, lon=34.9):
    return {
        "candidate_id": identifier,
        "start_timestamp": timestamp,
        "end_timestamp": timestamp,
        "centroid_latitude": lat,
        "centroid_longitude": lon,
        "hotspot_count": "2",
        "max_frp": "10.0",
        "mean_frp": "8.0",
        "satellites": "N20",
        "source_products": "VIIRS_NOAA20_SP",
        "duration_hours": "0",
    }


def official_row(year=2024, month=6, code="0123", scenario="שריפת יער", count=7):
    return {
        "year": str(year),
        "month": str(month),
        "settlement_lamas_code": code,
        "scenario": scenario,
        "event_count": str(count),
    }


def spatial_index():
    return SettlementSpatialIndex(settlement_polygons(boundary_collection()))


def test_point_inside_polygon_maps_name_and_lamas_code():
    match = spatial_index().locate(31.9, 34.9)
    assert match.settlement == "עיר א"
    assert match.lamas_code == "0123"


def test_boundary_feature_without_lamas_code_is_not_invented():
    collection = boundary_collection()
    collection["features"].append(
        {
            "type": "Feature",
            "properties": {"Muni_Heb": "ללא קוד"},
            "geometry": square(34.0, 30.0, 34.1, 30.1),
        }
    )
    validate_boundary_geojson(collection)
    polygons = settlement_polygons(collection)
    assert all(polygon.settlement != "ללא קוד" for polygon in polygons)


def test_point_outside_polygons_is_unlocated():
    output = match_candidates([candidate(lat=31.0, lon=34.0)], spatial_index(), {})
    assert output[0]["settlement"] == ""
    assert output[0]["settlement_lamas_code"] == ""
    assert output[0]["settlement_match_status"] == "outside_official_settlement_polygon"
    assert output[0]["official_month_support"] == "false"
    assert output[0]["firms_candidates_same_settlement_month"] == 0
    assert output[0]["ground_truth_status"] == "unlocated"


def test_local_committee_lamas_code_is_preferred_when_present():
    match = spatial_index().locate(31.85, 35.15)
    assert match.settlement == "יישוב ב"
    assert match.lamas_code == "0456"
    assert normalize_lamas_code("456.0") == "0456"


def test_same_year_month_and_settlement_has_official_month_support():
    official = build_official_index([official_row()])
    output = match_candidates([candidate()], spatial_index(), official)[0]
    assert output["official_month_support"] == "true"
    assert output["firms_candidates_same_settlement_month"] == 1
    assert output["official_event_count"] == 7
    assert output["official_scenarios"] == "שריפת יער"
    assert output["ground_truth_status"] == "supported"


def test_wrong_month_has_no_official_match():
    official = build_official_index([official_row(month=7)])
    output = match_candidates([candidate()], spatial_index(), official)[0]
    assert output["official_month_support"] == "false"
    assert output["ground_truth_status"] == "unsupported"


def test_wrong_settlement_has_no_official_match():
    official = build_official_index([official_row(code="0456")])
    output = match_candidates([candidate()], spatial_index(), official)[0]
    assert output["official_month_support"] == "false"


def test_irrelevant_scenarios_are_excluded():
    official = build_official_index(
        [
            official_row(scenario="פסולת"),
            official_row(scenario="מדורה ללא השגחה"),
        ]
    )
    assert official == {}


def test_multiple_relevant_scenarios_are_aggregated():
    official = build_official_index(
        [
            official_row(scenario="שריפת יער", count=2),
            official_row(scenario="שריפת צמחייה באינדקס רגיל", count=5),
            official_row(scenario="שריפת צמחייה באינדקס גבוה / קיצון", count=3),
        ]
    )
    output = match_candidates([candidate()], spatial_index(), official)[0]
    assert output["official_event_count"] == 10
    assert output["official_scenarios"].split(";") == sorted(
        [
            "שריפת יער",
            "שריפת צמחייה באינדקס רגיל",
            "שריפת צמחייה באינדקס גבוה / קיצון",
        ]
    )


def test_monthly_count_is_not_allocated_one_to_one_between_candidates():
    official = build_official_index([official_row(count=7)])
    output = match_candidates(
        [candidate("candidate-1"), candidate("candidate-2")], spatial_index(), official
    )
    assert [row["official_event_count"] for row in output] == [7, 7]
    assert [row["firms_candidates_same_settlement_month"] for row in output] == [2, 2]
    assert all(row["ground_truth_status"] == "supported" for row in output)
    assert all("confirmed_incident" not in row for row in output)


def test_candidate_count_is_scoped_to_settlement_and_calendar_month():
    output = match_candidates(
        [
            candidate("june-1"),
            candidate("june-2"),
            candidate("july", "2024-07-01T00:00:00Z"),
        ],
        spatial_index(),
        {},
    )
    counts = {row["candidate_id"]: row["firms_candidates_same_settlement_month"] for row in output}
    assert counts == {"june-1": 2, "june-2": 2, "july": 1}


def test_output_is_deterministic_for_input_order():
    official = build_official_index([official_row()])
    first = candidate("a", "2024-06-01T00:00:00Z")
    second = candidate("b", "2024-06-02T00:00:00Z")
    assert match_candidates([second, first], spatial_index(), official) == match_candidates(
        [first, second], spatial_index(), official
    )
