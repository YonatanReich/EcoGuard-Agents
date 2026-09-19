"""Rule-based candidate detection for Hebrew Telegram fire reports.

The result identifies messages worth further verification. It does not verify
that a fire exists and performs no network, source-reputation, or AI analysis.
"""

import re
import unicodedata


FIRE_CANDIDATE_THRESHOLD = 0.60

STRONG_FIRE_TERMS = {
    "שריפה": (
        "שריפה",
        "שרפה",
        "לשריפה",
        "לשרפה",
        "בשריפה",
        "בשרפה",
        "השריפה",
        "השרפה",
    ),
    "שריפת": ("שריפת", "בשריפת"),
    "עולה באש": ("עולה באש",),
    "עלה באש": ("עלה באש",),
    "עלתה באש": ("עלתה באש",),
    "בוער": ("בוער",),
    "בוערת": ("בוערת",),
    "בוערים": ("בוערים",),
    "להבות": ("להבות",),
    "מוקד בעירה": ("מוקד בעירה",),
    "מוקד הבעירה": ("מוקד הבעירה",),
}

SMOKE_TERMS = (
    "זיהוי עשן",
    "עשן סמיך",
    "עשן כבד",
    "עשן שחור",
    "עשן עולה",
    "ריח שרוף",
)

CONTEXT_TERMS = (
    "מבנה",
    "בניין",
    "בית",
    "דירה",
    "מחסן",
    "מפעל",
    "רכב",
    "משאית",
    "אוטובוס",
    "שטח פתוח",
    "יער",
    "חורש",
    "צמחייה",
    "קוצים",
    "שדה",
    "מתפשט",
    "מתפשטת",
    "התפשטה",
    "מסכנת",
    "לוחמי האש",
    "צוותי כיבוי",
    "פעולות כיבוי",
    "הושגה שליטה",
    "נבלמה",
)

AMBIGUOUS_TERMS = (
    "בקבוק תבערה",
    "בקבוקי תבערה",
    "מטען תבערה",
    "פתח באש",
    "פתחה באש",
    "חילופי אש",
    "אש חיה",
    "ירי",
    "פיצוץ",
    "התפוצץ",
    "דוד שמש שהתפוצץ",
)

RESOLVED_OR_NEGATED_TERMS = (
    "אין שריפה",
    "אין חשש לשריפה",
    "השריפה כובתה",
    "האירוע הסתיים",
    "הושגה שליטה",
)

_NIQQUD_PATTERN = re.compile(
    "[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]"
)


def _normalize_text(text: str) -> str:
    without_niqqud = _NIQQUD_PATTERN.sub("", text)
    punctuation_normalized = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in without_niqqud
    )
    return " ".join(punctuation_normalized.casefold().split())


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.search(pattern, text) is not None


def _find_strong_terms(text: str) -> list[str]:
    return [
        canonical_term
        for canonical_term, variants in STRONG_FIRE_TERMS.items()
        if any(_contains_phrase(text, variant) for variant in variants)
    ]


def _find_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if _contains_phrase(text, term)]


def _find_context_terms(text: str) -> list[str]:
    prefix_pattern = "[בלמהוכ]?"
    matched_terms = []

    for term in CONTEXT_TERMS:
        phrase_pattern = re.escape(term).replace(r"\ ", r"\s+")
        pattern = rf"(?<!\w){prefix_pattern}{phrase_pattern}(?!\w)"
        if re.search(pattern, text) is not None:
            matched_terms.append(term)

    return matched_terms


def detect_fire_candidate(text: str | None) -> dict:
    """Return a deterministic first-stage fire-candidate assessment."""
    if text is None or not text.strip():
        return {
            "is_fire_candidate": False,
            "matched_terms": [],
            "confidence": 0.0,
            "reason": "No message text was provided.",
        }

    normalized_text = _normalize_text(text)
    strong_terms = _find_strong_terms(normalized_text)
    smoke_terms = _find_terms(normalized_text, SMOKE_TERMS)
    context_terms = _find_context_terms(normalized_text)
    ambiguous_terms = _find_terms(normalized_text, AMBIGUOUS_TERMS)
    resolved_terms = _find_terms(normalized_text, RESOLVED_OR_NEGATED_TERMS)
    matched_terms = strong_terms + smoke_terms + context_terms + ambiguous_terms

    if resolved_terms:
        confidence = 0.2
        matched_terms.extend(resolved_terms)
        reason = "The message explicitly negates or resolves the reported fire."
    elif strong_terms:
        confidence = min(1.0, 0.85 + 0.05 * len(context_terms))
        reason = "Explicit active-fire language was found."
        if context_terms:
            reason = (
                "Explicit active-fire language was found with supporting "
                "incident context."
            )
    elif smoke_terms:
        confidence = min(0.75, 0.60 + 0.05 * len(context_terms))
        reason = "A smoke indicator was found and requires further verification."
        if context_terms:
            reason = "A smoke indicator was found with supporting incident context."
    elif ambiguous_terms:
        confidence = 0.10
        reason = (
            "Only ambiguous emergency language was found, without independent "
            "evidence of an active fire."
        )
    else:
        confidence = 0.0
        reason = "No explicit fire or smoke indicator was found."

    confidence = round(confidence, 2)
    return {
        "is_fire_candidate": confidence >= FIRE_CANDIDATE_THRESHOLD,
        "matched_terms": matched_terms,
        "confidence": confidence,
        "reason": reason,
    }
