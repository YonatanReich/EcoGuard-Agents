"""Focused tests for the rule-based Telegram fire candidate filter."""

import pytest

from agents.telegram_fire_candidate_filter import detect_fire_candidate


MATCHING_MESSAGES = (
    "רמלה משה לוי שריפה במבנה",
    "שריפה בשטח פתוח שנבלמה על ידי לוחמי האש",
    "משאית עולה באש בפתח תקווה",
    "שריפת אוטובוס מחלף פולג",
    "פתח תקווה זיהוי עשן",
    "בקבוק תבערה הושלך וגרם לשריפה במבנה",
)

NON_MATCHING_MESSAGES = (
    "דוד שמש שהתפוצץ בירושלים",
    "נזרקו בקבוקי תבערה",
    "החשוד פתח באש לעבר השוטרים",
    "חילופי אש באזור",
    "תאונת דרכים בין שני כלי רכב",
    "פועל חולץ מאתר בנייה",
    "לוחמי האש חילצו פועל שנפל מגובה",
)


@pytest.mark.parametrize("text", MATCHING_MESSAGES)
def test_expected_fire_candidates_match(text: str):
    result = detect_fire_candidate(text)

    assert result["is_fire_candidate"] is True
    assert result["confidence"] >= 0.60
    assert result["matched_terms"]


@pytest.mark.parametrize("text", NON_MATCHING_MESSAGES)
def test_unrelated_or_ambiguous_messages_do_not_match(text: str):
    result = detect_fire_candidate(text)

    assert result["is_fire_candidate"] is False
    assert result["confidence"] < 0.60


def test_independent_fire_evidence_overrides_ambiguous_phrase():
    result = detect_fire_candidate(
        "בקבוק תבערה הושלך וגרם לשריפה במבנה"
    )

    assert result["is_fire_candidate"] is True
    assert "שריפה" in result["matched_terms"]
    assert "בקבוק תבערה" in result["matched_terms"]


@pytest.mark.parametrize("text", [None, "", "   \n\t"])
def test_missing_or_blank_text_does_not_match(text: str | None):
    result = detect_fire_candidate(text)

    assert result == {
        "is_fire_candidate": False,
        "matched_terms": [],
        "confidence": 0.0,
        "reason": "No message text was provided.",
    }


def test_niqqud_and_punctuation_are_normalized():
    result = detect_fire_candidate("שְׂרֵפָה, בְּמִבְנֶה!")

    assert result["is_fire_candidate"] is True
    assert "שריפה" in result["matched_terms"]
    assert "מבנה" in result["matched_terms"]


@pytest.mark.parametrize(
    ("text", "context_term"),
    [
        ("שריפה במבנה", "מבנה"),
        ("שריפה בחורש", "חורש"),
        ("דיווח על שריפה למשאית", "משאית"),
    ],
)
def test_common_prefixes_are_removed_only_for_known_context_terms(
    text: str,
    context_term: str,
):
    result = detect_fire_candidate(text)

    assert result["is_fire_candidate"] is True
    assert context_term in result["matched_terms"]


def test_prefixed_context_alone_does_not_create_a_candidate():
    result = detect_fire_candidate("המבנה נבדק ונמצא תקין")

    assert result["is_fire_candidate"] is False
    assert result["confidence"] == 0.0
    assert "מבנה" in result["matched_terms"]


@pytest.mark.parametrize(
    ("text", "context_term"),
    [("בחורשה נערך טיול", "חורש"), ("למשאיות יש נתיב", "משאית")],
)
def test_context_terms_do_not_match_inside_longer_words(
    text: str,
    context_term: str,
):
    result = detect_fire_candidate(text)

    assert result["is_fire_candidate"] is False
    assert result["confidence"] == 0.0
    assert context_term not in result["matched_terms"]
