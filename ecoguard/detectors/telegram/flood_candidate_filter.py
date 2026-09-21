"""Conservative deterministic classification of Hebrew Flood reports."""

from __future__ import annotations

import re
import unicodedata


FLOOD_CANDIDATE_THRESHOLD = 0.70

# These phrases describe current conditions or completed emergency actions.
# Generic weather, forecasts and the noun "rain" are deliberately absent.
OCCURRENCE_TERMS = (
    "בשל הצפות",
    "בעקבות הצפות",
    "זרימות חזקות והצפות",
    "כביש מוצף",
    "כבישים מוצפים",
    "מים על הכביש",
    "מים בכביש",
    "נחסם בעקבות שיטפון",
    "נחסם בעקבות שטפון",
    "חילוץ מהמים",
    "רכב נלכד במים",
    "רכב נסחף במים",
    "הצפה",
    "הצפות",
)

FORECAST_OR_WARNING_TERMS = (
    "חשש לשיטפונות",
    "צפי לשיטפונות",
    "סיכוי לשיטפונות",
    "עלול לגרום לשיטפונות",
    "צפויים שיטפונות",
    "חשש להתפתחות שיטפונות",
)

SAFETY_BOILERPLATE = (
    "להימנע מהגעה לאזורי שיטפונות נחלים כבישים מוצפים",
)
RESOLVED_OR_NEGATED_TERMS = (
    "אין הצפה", "אין חשש להצפות", "אין חשש לשיטפונות",
    "הכביש נפתח", "נפתח לתנועה", "חזר לתנועה", "המים ירדו",
    "האירוע הסתיים", "ההצפה הסתיימה",
)

_NIQQUD = re.compile("[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]")


def _normalize(text: str) -> str:
    text = _NIQQUD.sub("", text)
    text = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in text
    )
    return " ".join(text.casefold().split())


def _matches(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text]


def detect_flood_candidate(text: str | None) -> dict:
    if text is None or not text.strip():
        return {
            "is_flood_candidate": False,
            "matched_terms": [],
            "confidence": 0.0,
            "reason": "No message text was provided.",
        }
    normalized = _normalize(text)
    resolved = _matches(normalized, RESOLVED_OR_NEGATED_TERMS)
    warnings = _matches(normalized, FORECAST_OR_WARNING_TERMS)
    boilerplate = _matches(normalized, SAFETY_BOILERPLATE)

    occurrence_text = normalized
    for phrase in (*FORECAST_OR_WARNING_TERMS, *SAFETY_BOILERPLATE):
        occurrence_text = occurrence_text.replace(phrase, " ")
    occurrence_text = " ".join(occurrence_text.split())
    occurrences = _matches(occurrence_text, OCCURRENCE_TERMS)
    matched = list(dict.fromkeys([*occurrences, *warnings, *boilerplate, *resolved]))

    if resolved:
        confidence = 0.2
        reason = "The message explicitly negates or resolves the flooding condition."
    elif occurrences:
        confidence = min(1.0, 0.85 + 0.05 * (len(occurrences) > 1))
        reason = "Explicit current flooding or flood-response language was found."
    elif warnings:
        confidence = 0.1
        reason = "Only forecast or flood-warning language was found."
    elif boilerplate:
        confidence = 0.0
        reason = "Only generic flood-safety boilerplate was found."
    else:
        confidence = 0.0
        reason = "No explicit flood or specific water-impact combination was found."

    confidence = round(confidence, 2)
    return {
        "is_flood_candidate": confidence >= FLOOD_CANDIDATE_THRESHOLD,
        "matched_terms": matched,
        "confidence": confidence,
        "reason": reason,
    }
