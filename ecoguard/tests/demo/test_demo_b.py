from collections import Counter
from datetime import datetime, timezone

from ecoguard.api.scenario import SCENARIOS
from ecoguard.demo.grade import _closest
from ecoguard.demo.scenarios import demo_b
from ecoguard.shared.cells import are_adjacent


NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def test_demo_b_is_registered_and_contains_all_eight_events():
    assert SCENARIOS["demo_b"] == "ecoguard.demo.scenarios.demo_b"
    assert [event["id"] for event in demo_b.GROUND_TRUTH] == [
        "B1",
        "B2",
        "B3",
        "B4",
        "B5",
        "B6",
        "B7",
        "B8",
    ]
    assert {event["hazard"] for event in demo_b.GROUND_TRUTH} == {
        "fire",
        "flood",
        "earthquake",
        "air_pollution",
    }
    assert "expect_allocation" not in demo_b.GROUND_TRUTH[0]
    assert "expect_allocation" not in demo_b.GROUND_TRUTH[1]
    assert all(
        event["expect_allocated_units"] == ["police"]
        for event in (
            demo_b.GROUND_TRUTH[2],
            demo_b.GROUND_TRUTH[3],
            demo_b.GROUND_TRUTH[4],
        )
    )
    assert all(
        event["expect_allocated_units"] == []
        for event in (demo_b.GROUND_TRUTH[5], demo_b.GROUND_TRUTH[6])
    )


def test_demo_b_builds_collector_shaped_structured_observations():
    rows = demo_b.build_rows(NOW)

    assert len(rows) == 31
    assert Counter(source for source, *_ in rows) == {
        "firms": 8,
        "weather": 4,
        "water_authority_hydrometric_observations": 6,
        "gsi_earthquake": 5,
        "air_pollution": 4,
        "telegram": 4,
    }
    assert all(observed.tzinfo is not None for _, _, observed, _ in rows)


def test_demo_b_fire_cells_pin_merge_and_separation_boundaries():
    assert are_adjacent(
        demo_b.JERUSALEM_HILLS_CELL,
        demo_b.JERUSALEM_HILLS_SPREAD_CELL,
    )
    assert not are_adjacent(
        demo_b.JERUSALEM_HILLS_CELL,
        demo_b.BEIT_SHEMESH_CELL,
    )
    assert not are_adjacent(
        demo_b.JERUSALEM_HILLS_SPREAD_CELL,
        demo_b.BEIT_SHEMESH_CELL,
    )


def test_demo_b_keeps_the_two_earthquake_regions_separate():
    quakes = [
        payload
        for source, _cell, _observed, payload in demo_b.build_rows(NOW)
        if source == "gsi_earthquake"
    ]

    assert [quake["magnitude"] for quake in quakes] == [5.4, 4.3, 3.9, 4.8, 3.4]
    assert sum(quake["magnitude"] >= 3.5 for quake in quakes) == 4
    assert are_adjacent(demo_b.TIBERIAS_CELL, demo_b.TIBERIAS_AFTERSHOCK_CELL)
    assert not are_adjacent(demo_b.TIBERIAS_CELL, demo_b.EILAT_QUAKE_CELL)


def test_demo_b_forwarded_ashdod_reports_share_one_origin():
    reports = [
        payload
        for source, _cell, _observed, payload in demo_b.build_rows(NOW)
        if source == "telegram" and "אשדוד" in payload["raw_text"]
    ]

    assert len(reports) == 3
    assert {
        (
            report["forwarded_provenance"]["origin_peer_id"],
            report["forwarded_provenance"]["origin_message_id"],
        )
        for report in reports
    } == {(-1009000000001, 7001)}


def test_demo_b_netanya_has_text_and_satellite_evidence():
    rows = demo_b.build_rows(NOW)
    netanya_firms = [
        payload
        for source, cell, _observed, payload in rows
        if source == "firms" and cell == demo_b.NETANYA_CELL
    ]
    netanya_reports = [
        payload
        for source, _cell, _observed, payload in rows
        if source == "telegram" and "נתניה" in payload["raw_text"]
    ]

    assert len(netanya_firms) == 2
    assert len(netanya_reports) == 1


def test_grader_does_not_reuse_one_incident_for_two_expected_events():
    incidents = [
        {"id": "INC-1", "latitude": 31.78, "longitude": 35.12},
        {"id": "INC-2", "latitude": 31.74, "longitude": 34.99},
    ]

    first, _ = _closest(incidents, demo_b.GROUND_TRUTH[0])
    second, _ = _closest(
        incidents,
        demo_b.GROUND_TRUTH[1],
        excluded={first["id"]},
    )

    assert first["id"] == "INC-1"
    assert second["id"] == "INC-2"
