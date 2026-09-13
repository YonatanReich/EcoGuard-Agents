"""Retention must never be able to delete the things that cannot be rebuilt.

The danger here is not that a number is slightly wrong — it is that a policy
gets applied uniformly. Weather is a cache of something Open-Meteo will serve
again; the FWI chain is an accumulator computed from its own previous row, and
deleting it destroys months of drought memory that no later collection
recovers. Telegram is the only copy of text that gets edited and deleted
upstream.

So these pin the *shape* of the policy rather than its exact days: that the
irrecoverable sources are explicitly kept, that every collector has a
deliberate entry, and that an unknown source is left alone rather than swept up
by somebody else's default.
"""

import pytest

from ecoguard.retention import RETENTION_DAYS

# Sources whose rows cannot be re-fetched from anywhere if deleted.
IRRECOVERABLE = ("fwi", "firms", "telegram")


@pytest.mark.parametrize("source", IRRECOVERABLE)
def test_irrecoverable_sources_are_never_pruned(source):
    # fwi is our own accumulator, firms NRT ages out upstream, and telegram
    # messages get edited and deleted at the source.
    assert RETENTION_DAYS[source] is None


def test_every_scheduled_collector_has_a_deliberate_policy():
    from ecoguard.scheduler import COLLECTORS

    # A collector with no entry is left untouched and warned about, which is
    # safe but silent. This makes adding one a conscious decision instead.
    missing = set(COLLECTORS) - set(RETENTION_DAYS)
    assert not missing, f"no retention decided for: {sorted(missing)}"


def test_the_two_largest_sources_are_the_ones_actually_bounded():
    # Weather and forecast are 96% of the growth. If either became "keep
    # forever" the policy would stop doing its job while still looking present.
    assert RETENTION_DAYS["weather"] is not None
    assert RETENTION_DAYS["weather_forecast"] is not None


def test_weather_is_kept_well_past_the_feature_window():
    from ecoguard.database.repositories.weather_history import HISTORY_HOURS

    # compute_features reads 168 hours behind an evaluation time. Pruning
    # anywhere near that would silently truncate every weather feature.
    assert RETENTION_DAYS["weather"] * 24 > HISTORY_HOURS * 3


def test_fire_history_windows_outlive_their_sources_retention():
    from ecoguard.database.repositories.fire_history import HISTORY_WINDOWS

    # The longest window is 365 days. FIRMS is kept forever, so this holds by
    # construction — the test exists to catch someone "tidying up" firms into
    # a finite retention without noticing the features depend on a year.
    longest = max(days for _, _, days in HISTORY_WINDOWS)
    assert RETENTION_DAYS["firms"] is None, (
        f"fire history reads {longest} days back; firms cannot be pruned"
    )


def test_persistence_needs_more_history_than_any_prune_would_leave():
    from ecoguard.database.repositories.fire_history import PERSISTENCE_MIN_DAYS

    assert RETENTION_DAYS["firms"] is None
    assert PERSISTENCE_MIN_DAYS >= 60


def test_an_unknown_source_is_not_swept_up_by_a_default():
    # No catch-all key, and no fallback in the code path: a source nobody
    # decided about keeps its rows.
    assert "*" not in RETENTION_DAYS
    assert None not in RETENTION_DAYS


def test_retention_days_are_positive_where_set():
    for source, days in RETENTION_DAYS.items():
        assert days is None or days > 0, f"{source} has a non-positive retention"
