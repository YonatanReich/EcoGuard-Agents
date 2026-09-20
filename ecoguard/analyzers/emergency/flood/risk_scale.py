"""Flood severity mapping onto the existing shared Fire risk scale."""

from __future__ import annotations

from ecoguard.shared.schemas import risk_level_for_score


FLOOD_OPERATIONAL_RISK_SCORE_BY_SEVERITY: dict[int, int] = {
    3: 40,
    4: 60,
    5: 80,
    6: 100,
}


def flood_operational_risk(severity_level: int) -> tuple[int, str]:
    """Return a 0-100 score and the level derived by the existing Fire scale."""

    try:
        score = FLOOD_OPERATIONAL_RISK_SCORE_BY_SEVERITY[severity_level]
    except KeyError as error:
        raise ValueError("active Flood severity must be between 3 and 6") from error
    level = risk_level_for_score(score)
    if level is None:  # Defensive: every configured score is numeric.
        raise ValueError("Flood operational risk score is unavailable")
    return score, level


__all__ = [
    "FLOOD_OPERATIONAL_RISK_SCORE_BY_SEVERITY",
    "flood_operational_risk",
]
