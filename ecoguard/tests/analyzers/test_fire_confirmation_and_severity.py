"""Is it a fire, and does what surrounds it change how bad it is.

Two requirements the analyser did not meet until now. It assumed every
incident was a real fire, and it scored a blaze at a fuel depot exactly as it
scored the same blaze on empty ground.

All pure: every locality and site is passed in, so none of this touches the
store.
"""

from datetime import datetime, timezone

import pytest

from ecoguard.analyzers.emergency.fire import confirmation, infrastructure
from ecoguard.analyzers.emergency.fire.spread_analyzer import analyze

WHEN = datetime(2026, 8, 14, 13, 40, tzinfo=timezone.utc)

DRY_AND_WINDY = {
    "temperature_c": 40.0, "humidity_percent": 12.0,
    "wind_speed_kmh": 45.0, "wind_direction_deg": 90.0,
    "slope_deg": 8.0, "slope_max_deg": 18.0, "aspect_deg": 270.0,
    "cover_fractions": {"shrubland": 0.6, "grassland": 0.3, "tree_cover": 0.1},
    "gaps": [],
}


def _incident(**overrides):
    evidence = {
        "hotspot_count": 9,
        "satellites": ["VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT"],
        "detection_share": 0.003,
        "recent_detections": [],
        **overrides.pop("evidence", {}),
    }
    return {
        "id": "TEST",
        "primary_hazard": "fire",
        "latitude": 31.5,
        "longitude": 34.9,
        "cells": ["risk-05000m-r0050-c0010"],
        "last_signal_at": WHEN,
        "signal_count": overrides.pop("signal_count", 3),
        "signals": [{
            "hazard": "fire",
            "value": overrides.pop("frp", 90.0),
            "confidence": overrides.pop("confidence", 0.9),
            "evidence": evidence,
        }],
        **overrides,
    }


def _site(category, kind="thing", lat=31.505, lon=34.86):
    """A site in the shape `sites_at_risk` produces, which is what analyze takes."""
    return {
        "name": kind, "kind": kind, "category": category,
        "latitude": lat, "longitude": lon, "osm_id": "way/1",
        "exposure": "likely", "distance_m": 800.0, "bearing_deg": 270.0,
    }


# --- requirement 1: is there actually a fire -------------------------------

def test_several_instruments_and_high_power_is_a_confirmed_fire():
    assessment = confirmation.assess(_incident())
    assert assessment["verdict"] == confirmation.CONFIRMED
    assert any(
        item["factor"] == "independent_instruments"
        for item in assessment["reasons"]
    )


def test_a_lone_weak_pixel_in_a_busy_cell_is_not_confirmed():
    assessment = confirmation.assess(_incident(
        frp=3.0, confidence=0.45, signal_count=1,
        evidence={"hotspot_count": 1, "satellites": ["MODIS_NRT"],
                  "detection_share": 0.4},
    ))
    assert assessment["verdict"] in (confirmation.POSSIBLE, confirmation.DOUBTFUL)


def test_a_known_standing_source_overrides_otherwise_decent_evidence():
    """The steel works case. Whatever else is true, this cell lights nightly."""
    assessment = confirmation.assess(
        _incident(frp=3.0, confidence=0.45, signal_count=1,
                  evidence={"hotspot_count": 1, "satellites": ["MODIS_NRT"],
                            "detection_share": 0.4}),
        history={"persistent": True, "distinct_days": 260, "span_days": 365},
    )
    assert assessment["verdict"] == confirmation.DOUBTFUL
    assert any(
        item["factor"] == "standing_thermal_source"
        for item in assessment["reasons"]
    )


def test_a_rising_power_curve_counts_toward_a_fire():
    assessment = confirmation.assess(_incident(evidence={
        "recent_detections": [
            {"peak_frp_mw": 4.7}, {"peak_frp_mw": 18.6}, {"peak_frp_mw": 71.6},
        ],
    }))
    assert any(
        item["factor"] == "intensity_growing" for item in assessment["reasons"]
    )


def test_a_flat_trace_counts_against_one():
    assessment = confirmation.assess(_incident(
        frp=2.0, signal_count=6,
        evidence={"detection_share": 0.4, "hotspot_count": 1,
                  "satellites": ["MODIS_NRT"],
                  "recent_detections": [{"peak_frp_mw": 2.0}] * 6},
    ))
    assert any(item["factor"] == "flat_output" for item in assessment["reasons"])


def test_no_evidence_is_unassessed_and_never_doubtful():
    """Absence of evidence must not become evidence of absence.

    `doubtful` is a judgement against the fire; `unassessed` is the absence of
    anything to judge. Collapsing them makes a missing field into an argument,
    and then caps the severity of a fire nobody has actually doubted.
    """
    assessment = confirmation.assess({"signals": []})
    assert assessment["verdict"] == confirmation.UNASSESSED
    assert assessment["score"] is None, "an unassessed detection has no score"
    assert "not evidence of absence" in assessment["reasons"][0]["detail"]


def test_an_unassessed_detection_does_not_cap_severity():
    unassessed = {**_incident(), "signals": []}
    result = analyze(unassessed, DRY_AND_WINDY, horizon_minutes=180, localities=[])
    assert result["detection"]["verdict"] == confirmation.UNASSESSED
    assert result["risk_score"] >= 55, "a missing field must not lower severity"


def test_every_verdict_carries_its_reasons():
    for assessment in (
        confirmation.assess(_incident()),
        confirmation.assess({"signals": []}),
    ):
        assert assessment["reasons"], "a verdict with no reasons cannot be argued with"
        assert confirmation.statement(assessment)


# --- requirement 5: what else is in the path -------------------------------

def _severity_with(sites):
    result = analyze(
        _incident(), DRY_AND_WINDY, horizon_minutes=180,
        localities=[], sites=sites,
    )
    assert result["status"] == "ok", result["reason"]
    return result


def test_the_same_fire_scores_higher_next_to_a_hazard_than_on_empty_ground():
    """The defence-plant versus secluded-beach case, stated as a test."""
    empty = _severity_with([])
    beside_a_hazard = _severity_with([_site(infrastructure.HAZARD, "fuel depot")])

    assert beside_a_hazard["risk_score"] > empty["risk_score"]


def test_a_hazard_outranks_an_economic_site():
    economic = _severity_with([_site(infrastructure.ECONOMIC, "retail area")])
    hazard = _severity_with([_site(infrastructure.HAZARD, "power plant")])
    assert hazard["risk_score"] > economic["risk_score"]


def test_a_category_is_counted_once_however_many_sites_it_has():
    """Otherwise a well-surveyed industrial estate outranks a hospital."""
    one = _severity_with([_site(infrastructure.ECONOMIC, "industrial area")])
    many = _severity_with([
        _site(infrastructure.ECONOMIC, f"unit {index}") for index in range(12)
    ])
    assert one["risk_score"] == many["risk_score"]


def test_the_report_names_what_else_is_in_the_path():
    result = _severity_with([_site(infrastructure.LIFE_SAFETY, "hospital")])
    assert "OTHER SITES IN THE PATH" in result["report"]
    assert "hospital" in result["report"]


def test_an_empty_path_says_so_without_claiming_nothing_is_there():
    result = _severity_with([])
    assert "OTHER SITES IN THE PATH" in result["report"]
    assert "not proof that there is nothing there" in result["report"]


# --- the two requirements meeting --------------------------------------------

def test_a_doubtful_detection_caps_severity():
    """A 90-point forecast on one dubious pixel is a confident wrong answer."""
    doubtful = _incident(
        frp=3.0, confidence=0.45, signal_count=1,
        evidence={"hotspot_count": 1, "satellites": ["MODIS_NRT"],
                  "detection_share": 0.4},
    )
    result = analyze(
        doubtful, DRY_AND_WINDY, horizon_minutes=180, localities=[],
        sites=[_site(infrastructure.HAZARD, "power plant")],
        fire_history={"persistent": True, "distinct_days": 260, "span_days": 365},
    )
    verdict = result["detection"]["verdict"]
    assert verdict == confirmation.DOUBTFUL
    assert result["risk_score"] <= 35, "severity must be capped by detection doubt"


def test_the_detection_verdict_leads_the_report():
    result = _severity_with([])
    assert result["report"].startswith("DETECTION")


@pytest.mark.parametrize("category", [
    infrastructure.HAZARD, infrastructure.LIFE_SAFETY, infrastructure.ECONOMIC,
])
def test_every_category_reaches_the_result(category):
    result = _severity_with([_site(category)])
    assert result["infrastructure_summary"]["counts"][category] == 1
