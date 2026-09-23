"""A message is judged on when it was published, not on when we happened to fetch it."""

from datetime import datetime, timedelta, timezone
import inspect

from ecoguard.database.repositories import text_candidates
from ecoguard.detectors.text import classifier


def test_the_query_bounds_message_age_as_well_as_arrival():
    """Two bounds, because they answer different questions.

    The Telegram collector re-reads the last fifty messages of every channel on
    every run, so any gap ends with days of backlog ingested at once and
    stamped as arriving now. An arrival-time filter alone sends all of it to
    the model as though it were news — measured at 500 messages against 15 on
    the live store.
    """
    source = inspect.getsource(text_candidates.unclassified_text_observations)
    assert "o.ingested_at > :since" in source, "arrival bound must stay"
    assert "o.observed_at > CAST(:published_after AS timestamptz)" in source, (
        "message age must be bounded too, or a re-fetch of old posts reads as news"
    )


def test_the_classifier_passes_an_age_bound():
    """The bound is useless if the one caller does not supply it."""
    source = inspect.getsource(classifier.classify_new_text)
    assert "published_after=" in source


def test_the_age_bound_is_optional_so_other_callers_are_unaffected():
    """Omitting it keeps the previous behaviour, for anything that wants every row."""
    signature = inspect.signature(text_candidates.unclassified_text_observations)
    assert signature.parameters["published_after"].default is None


def test_the_two_bounds_are_the_same_length_by_default():
    """One answer to "how far back is still now", shared with the detectors."""
    from ecoguard.detectors.shared.window import DEFAULT_MAX_CATCHUP

    assert classifier.DEFAULT_LOOKBACK == DEFAULT_MAX_CATCHUP
