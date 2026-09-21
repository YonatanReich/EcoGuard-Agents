"""The classifier, driven by a stub model so no call is made.

What is pinned here is not "does the model classify well" — that is the model's
job and it changes without this file changing. It is the wiring around it: that
an outage degrades to keywords instead of losing messages, that a batch keeps
its indexes straight, that the disagreement count means what the Phase 2
checkpoint says it means.
"""

from datetime import datetime, timezone

import pytest

from ecoguard.detectors.text.classifier import (
    BatchLabels,
    MessageLabels,
    TextClassifier,
    build_batch_text,
    disagreements,
    is_classifiable,
)
from ecoguard.detectors.text import classifier as classifier_module
from ecoguard.detectors.text.keywords import hazards_in, normalise

AT = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def message(observation_id: int, text: str, *, source_id: str = "telegram:-100") -> dict:
    return {
        "observation_id": observation_id,
        "source_id": source_id,
        "observed_at": AT,
        "handle": "example",
        "display_name": "Example",
        "text": text,
    }


class StubLLM:
    """Returns prepared labels, or raises, without touching the network."""

    def __init__(self, labels=None, error: Exception | None = None):
        self.labels = labels or []
        self.error = error
        self.calls = []

    def parse_structured(self, *, system_blocks, user_text, output_format, **kwargs):
        self.calls.append(user_text)
        if self.error is not None:
            raise self.error
        return BatchLabels(messages=self.labels)


# --- normalisation and pre-filtering ---------------------------------------

def test_niqqud_and_quote_variants_normalise_to_one_form():
    # The same acronym arrives three ways from three CMSes and must match one
    # pattern, not three.
    assert normalise('חומ״ס') == normalise('חומ"ס') == 'חומ"ס'
    assert normalise("שָׂרֵפָה") == "שרפה"


def test_pure_links_and_emoji_are_not_worth_a_model_call():
    assert not is_classifiable("https://example.test/article")
    assert not is_classifiable("🔥🔥🔥")
    assert not is_classifiable("   ")
    assert not is_classifiable(None)
    assert is_classifiable("שריפה ביער")
    # A link with real text alongside it still is.
    assert is_classifiable("שריפה ביער https://example.test/1")


def test_the_prompt_names_the_source_but_never_its_tier():
    # A model told "this is the police" reads the same sentence more
    # generously. Tier is the allowlist's judgement and is applied after.
    text = build_batch_text([
        {"text": "שריפה", "display_name": "Example", "handle": "example"},
    ])

    assert "[0] (Example) שריפה" in text
    for tier in ("authority", "media", "unofficial", "official"):
        assert tier not in text


# --- the model path --------------------------------------------------------

def test_labels_are_matched_back_to_messages_by_index():
    # The model may return them in any order; identity is the index, not the
    # position in the reply. Getting this wrong attaches a fire in Haifa to a
    # message about a football match.
    llm = StubLLM(labels=[
        MessageLabels(index=1, relevant=True, literal=True, in_israel=True,
                      hazards=["flood"], location_text="רחוב הרצל"),
        MessageLabels(index=0, relevant=False, literal=False, in_israel=True),
    ])

    results = TextClassifier(llm=llm).classify([
        message(10, "משחק הכדורגל נדחה"),
        message(11, "הצפות ברחוב הרצל"),
    ])

    by_id = {result["observation_id"]: result for result in results}
    assert by_id[11]["hazards"] == ["flood"]
    assert by_id[11]["location_text"] == "רחוב הרצל"
    assert by_id[10]["hazards"] == []


def test_a_message_can_carry_two_hazards():
    llm = StubLLM(labels=[
        MessageLabels(index=0, relevant=True, literal=True, in_israel=True,
                      hazards=["fire", "air_quality"]),
    ])

    results = TextClassifier(llm=llm).classify([
        message(1, "שריפה במפעל, עשן כבד מעל השכונה"),
    ])

    assert results[0]["hazards"] == ["fire", "air_quality"]


def test_batches_are_split_at_the_configured_size():
    llm = StubLLM(labels=[])
    TextClassifier(llm=llm, batch_size=2).classify(
        [message(index, "שריפה") for index in range(5)]
    )

    assert len(llm.calls) == 3


# --- the fallback ----------------------------------------------------------

def test_an_outage_degrades_to_keywords_instead_of_losing_messages():
    llm = StubLLM(error=RuntimeError("provider down"))

    results = TextClassifier(llm=llm).classify([
        message(1, "שריפה פרצה ביער בן שמן"),
        message(2, "משחק הכדורגל נדחה"),
    ])

    caught = next(r for r in results if r["observation_id"] == 1)
    assert caught["hazards"] == ["fire"]
    # Flagged, so a row the net produced is never read as a judgement.
    assert caught["classified_by"] == "keywords"
    assert caught["failure_reason"] == "RuntimeError"
    # One result per input, always — a message with no keyword hit still
    # produces a row saying so rather than vanishing.
    assert len(results) == 2


def test_the_fallback_does_not_claim_a_foreign_news_fire_is_local():
    # The first live fallback run labelled a Ukrainian strike on a Moscow
    # refinery as a fire in Israel. The net cannot read geography, so the
    # source kind answers it: Telegram channels here are Israeli, news feeds
    # carry the world.
    llm = StubLLM(error=RuntimeError("provider down"))

    results = TextClassifier(llm=llm).classify([
        message(1, 'מתקן נפט במוסקבה עלה באש', source_id="https://news.test/feed"),
        message(2, "שריפה פרצה ביער בן שמן", source_id="telegram:-100"),
    ])

    by_id = {result["observation_id"]: result for result in results}
    assert by_id[1]["in_israel"] is False
    assert by_id[2]["in_israel"] is True


# --- the Phase 2 checkpoint ------------------------------------------------

def test_disagreement_is_counted_per_hazard_not_overall():
    # Fire dominates this stream. A single overall number would stay healthy
    # while flood recall fell to nothing, which is the failure this exists to
    # make visible.
    llm = StubLLM(labels=[
        # Model says fire, keywords agree.
        MessageLabels(index=0, relevant=True, literal=True, in_israel=True,
                      hazards=["fire"]),
        # Model says flood, keywords missed it — a stem to add.
        MessageLabels(index=1, relevant=True, literal=True, in_israel=True,
                      hazards=["flood"]),
        # Keywords matched a metaphor, model correctly refused it.
        MessageLabels(index=2, relevant=False, literal=False, in_israel=True),
    ])

    results = TextClassifier(llm=llm).classify([
        message(1, "שריפה ביער"),
        message(2, "הרחוב מלא במים עד הברכיים"),
        message(3, "רעידת אדמה פוליטית בכנסת"),
    ])
    counts = disagreements(results)

    assert counts["fire"]["both"] == 1
    assert counts["flood"]["model_only"] == 1
    assert counts["earthquake"]["keywords_only"] == 1
    assert counts["air_quality"] == {"both": 0, "model_only": 0, "keywords_only": 0}


def test_fallback_rows_are_excluded_from_the_disagreement_count():
    # Comparing the net with itself would report perfect agreement during an
    # outage — the one time the number would be most misleading.
    llm = StubLLM(error=RuntimeError("provider down"))

    results = TextClassifier(llm=llm).classify([message(1, "שריפה ביער")])

    assert disagreements(results)["fire"] == {
        "both": 0, "model_only": 0, "keywords_only": 0
    }


def test_runtime_entry_reads_telegram_and_rss_in_one_batch(monkeypatch):
    messages = [
        message(1, "שריפה בחיפה", source_id="telegram:-1001"),
        message(2, "Fire in Haifa", source_id="https://ynet.test/rss"),
    ]
    seen = []
    stored = []

    class RecordingClassifier:
        def classify(self, batch):
            seen.extend(batch)
            return [{
                "observation_id": item["observation_id"],
                "source_id": item["source_id"],
                "observed_at": item["observed_at"],
                "hazards": ["fire"],
                "relevant": True,
                "literal": True,
                "in_israel": True,
                "update_type": "new",
                "location_text": "חיפה",
                "claim": item["text"],
                "details": {},
                "classified_by": "model",
                "model_version": "test",
                "keyword_hazards": ["fire"],
            } for item in batch]

    monkeypatch.setattr(
        classifier_module, "unclassified_text_observations", lambda **_: messages
    )
    monkeypatch.setattr(
        classifier_module, "store_candidates",
        lambda results: stored.extend(results) or len(results),
    )

    result = classifier_module.classify_new_text(classifier=RecordingClassifier())

    assert [item["source_id"] for item in seen] == [
        "telegram:-1001", "https://ynet.test/rss",
    ]
    assert len(stored) == 2
    assert result["messages"] == 2
    assert result["candidates"] == 2


# --- the keyword net -------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("שריפה פרצה ביער בן שמן", "fire"),
    ("הורגשה רעידת אדמה בעוצמה 4.1", "earthquake"),
    ("זיהום אוויר כבד באזור המפרץ", "air_quality"),
    ('דליפת חומ"ס במפעל', "air_quality"),
    ("Wildfire spreads near Jerusalem", "fire"),
    ("Strong earthquake felt across the region", "earthquake"),
])
def test_the_net_catches_each_hazard_in_both_languages(text, expected):
    assert expected in hazards_in(text)


def test_the_net_matches_metaphors_on_purpose():
    # Tuned for recall: a false positive costs one classification, a false
    # negative is a missed event. Rejecting the metaphor is the model's job,
    # and the test exists so nobody "fixes" this later.
    assert "earthquake" in hazards_in("רעידת אדמה פוליטית בכנסת")


def test_hebrew_prefixes_do_not_hide_a_hazard():
    # שריפה, השריפה, בשריפה, מהשריפה are the same word to a reader and four
    # different strings to a naive matcher.
    for form in ("שריפה", "השריפה", "בשריפה", "והשריפה"):
        assert "fire" in hazards_in(f"דיווח על {form} באזור"), form


def test_a_message_with_no_hazard_term_matches_nothing():
    assert hazards_in("טראמפ על איראן: השאלה אם ומתי") == {}
    assert hazards_in("") == {}
    assert hazards_in(None) == {}
