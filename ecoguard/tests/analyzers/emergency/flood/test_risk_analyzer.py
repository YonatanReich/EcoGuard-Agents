"""Deterministic operational-risk tests for detected Flood events."""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.analyzers.emergency.flood.event_analyzer import FloodEventAnalyzer
from ecoguard.analyzers.emergency.flood.risk_analysis_schemas import (
    FloodRiskAssessment,
)
from ecoguard.analyzers.emergency.flood.risk_analyzer import FloodRiskAnalyzer


AT = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
THRESHOLDS = [20.0, 35.0, 50.0, 80.0, 120.0, 170.0]


def _signal(*, severity, discharge, previous, confidence=0.9, at=AT):
    signal = {
        "cell_id": "31.75:35.20",
        "observed_at": at.isoformat(),
        "hazard": "flood",
        "value": discharge,
        "location": {"latitude": 31.75, "longitude": 35.2},
        "evidence": {
            "source_station_id": 417,
            "stream_id": 82,
            "current_discharge": discharge,
            "severity_level": severity,
            "threshold_vector_m3s": THRESHOLDS,
            "recent_discharges_m3s": [previous, discharge],
        },
    }
    if confidence is not None:
        signal["confidence"] = confidence
    return signal


def _analysis(*signals):
    return FloodEventAnalyzer(clock=lambda: AT + timedelta(hours=1)).analyze(
        {"id": "INC-FLOOD-1", "signals": list(signals)}
    )


@pytest.mark.parametrize(
    ("severity", "discharge", "score", "level"),
    [
        (3, 60.0, 40, "medium"),
        (4, 85.0, 60, "high"),
        (5, 125.0, 80, "critical"),
        (6, 175.0, 100, "critical"),
    ],
)
def test_detected_flood_uses_shared_operational_scale(
    severity, discharge, score, level
):
    result = FloodRiskAnalyzer(clock=lambda: AT).analyze(
        _analysis(
            _signal(
                severity=severity,
                discharge=discharge,
                previous=discharge - 2,
            )
        )
    )

    assert result.metadata.analysis_status == "success"
    assert result.risk_semantics == "detected_event_operational_risk"
    assert result.risk_score == score
    assert result.risk_level == level
    assert result.confidence == "high"
    assert result.hydrologic_severity_level == severity
    assert result.primary_drivers


def test_risk_analyzer_assesses_latest_detected_state_not_peak_history():
    result = FloodRiskAnalyzer(clock=lambda: AT).analyze(
        _analysis(
            _signal(severity=5, discharge=125.0, previous=122.0),
            _signal(
                severity=4,
                discharge=85.0,
                previous=125.0,
                at=AT + timedelta(minutes=10),
            ),
        )
    )

    assert result.risk_score == 60
    assert result.risk_level == "high"
    assert result.change_type == "deescalated"


def test_below_active_flood_threshold_has_no_operational_risk_score():
    result = FloodRiskAnalyzer(clock=lambda: AT).analyze(
        _analysis(_signal(severity=2, discharge=40.0, previous=38.0))
    )

    assert result.metadata.analysis_status == "unavailable"
    assert result.risk_score is None
    assert result.risk_level is None
    assert result.error == "active_flood_severity_unavailable"


def test_missing_signal_confidence_produces_partial_low_confidence_assessment():
    result = FloodRiskAnalyzer(clock=lambda: AT).analyze(
        _analysis(
            _signal(
                severity=4,
                discharge=85.0,
                previous=82.0,
                confidence=None,
            )
        )
    )

    assert result.metadata.analysis_status == "partial"
    assert result.risk_score == 60
    assert result.confidence == "low"
    assert any("confidence" in gap for gap in result.evidence_gaps)


def test_schema_rejects_level_that_does_not_match_shared_scale():
    with pytest.raises(ValueError, match="shared 0-100 scale"):
        FloodRiskAssessment(
            metadata={"timestamp": AT, "analysis_status": "success"},
            event_id="INC-FLOOD-1",
            risk_score=60,
            risk_level="medium",
            confidence="high",
            hydrologic_severity_level=4,
            return_period_years=20,
            alert_level="severe",
            change_type="initial",
            primary_drivers=["Q20 threshold observed"],
            explanation="Detected Flood operational risk is based on current Q20 severity.",
        )
