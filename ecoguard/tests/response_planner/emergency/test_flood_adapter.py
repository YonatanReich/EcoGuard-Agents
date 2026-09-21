"""Flood analyzer to shared emergency-planner boundary tests."""

from datetime import datetime, timezone

import pytest

from ecoguard.analyzers.emergency.flood.event_analyzer import FloodEventAnalyzer
from ecoguard.analyzers.emergency.flood.risk_analyzer import FloodRiskAnalyzer
from ecoguard.response_planner.emergency.adapters import (
    OperationalAnalysisUnavailable,
    build_flood_plan_input,
)


AT = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _signal():
    return {
        "cell_id": "31.75:35.20",
        "observed_at": AT.isoformat(),
        "hazard": "flood",
        "value": 85.0,
        "confidence": 0.9,
        "location": {"latitude": 31.75, "longitude": 35.2},
        "evidence": {
            "source_station_id": 417,
            "stream_id": 82,
            "current_discharge": 85.0,
            "severity_level": 4,
            "threshold_vector_m3s": [20, 35, 50, 80, 120, 170],
            "recent_discharges_m3s": [75.0, 85.0],
        },
    }


def test_flood_adapter_preserves_analysis_without_reclassification():
    analysis = FloodEventAnalyzer(clock=lambda: AT).analyze({
        "id": "INC-FLOOD-1",
        "signals": [_signal()],
    })

    risk = FloodRiskAnalyzer(clock=lambda: AT).analyze(analysis)
    result = build_flood_plan_input(analysis, risk)

    assert result.hazard_type == "flood"
    assert result.incident_id == "INC-FLOOD-1"
    assert result.location.model_dump() == {"latitude": 31.75, "longitude": 35.2}
    assert result.risk_context == {
        "risk_semantics": "detected_event_operational_risk",
        "risk_score": 60.0,
        "risk_level": "high",
        "confidence": "high",
        "risk_basis": "hydrometric_severity_mapping",
        "hydrologic_severity_level": 4,
        "return_period_years": 20,
        "alert_level": "severe",
        "change_type": "initial",
        "threshold_transition": None,
    }
    assert "Q20" in result.event_description
    assert result.additional_context["change_assessment"]["change_type"] == "initial"


def test_flood_adapter_rejects_unavailable_analysis():
    analysis = FloodEventAnalyzer(clock=lambda: AT).analyze({
        "id": "INC-FLOOD-1",
        "signals": [],
    })

    with pytest.raises(
        OperationalAnalysisUnavailable, match="flood_analysis_unavailable"
    ):
        build_flood_plan_input(
            analysis,
            FloodRiskAnalyzer(clock=lambda: AT).analyze(analysis),
        )


def test_flood_adapter_rejects_risk_for_another_incident():
    analysis = FloodEventAnalyzer(clock=lambda: AT).analyze({
        "id": "INC-FLOOD-1",
        "signals": [_signal()],
    })
    risk = FloodRiskAnalyzer(clock=lambda: AT).analyze(analysis).model_copy(
        update={"event_id": "INC-FLOOD-OTHER"}
    )

    with pytest.raises(
        OperationalAnalysisUnavailable,
        match="flood_risk_unavailable",
    ):
        build_flood_plan_input(analysis, risk)
