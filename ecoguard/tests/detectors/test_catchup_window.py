"""A detector that has been away resumes at the present, not where it stopped."""

from datetime import datetime, timedelta, timezone

import pytest

from ecoguard.detectors.shared.window import DEFAULT_MAX_CATCHUP, catchup_floor

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def test_a_recent_bookmark_is_used_unchanged():
    """Normal running is untouched: the floor only binds after a real gap."""
    bookmark = NOW - timedelta(minutes=10)
    assert catchup_floor(bookmark, NOW) == bookmark


def test_a_two_day_old_bookmark_does_not_reopen_two_days_of_events():
    """The case this exists for: detection paused on Tuesday, resumed on Thursday.

    Reading from the bookmark would open incidents for fires that burned out
    two days ago. A detector answers "is something happening", and an
    observation old enough to have finished happening cannot support that.
    """
    bookmark = NOW - timedelta(days=2)
    resumed = catchup_floor(bookmark, NOW)

    assert resumed == NOW - DEFAULT_MAX_CATCHUP
    assert resumed > bookmark
    assert NOW - resumed <= timedelta(hours=6)


def test_a_detector_that_has_never_run_still_starts_from_the_present():
    """No bookmark is not licence to read whatever the store happens to hold."""
    assert catchup_floor(None, NOW) == NOW - DEFAULT_MAX_CATCHUP


def test_a_naive_bookmark_is_read_as_utc_rather_than_crashing():
    """Some stores hand back a naive timestamp; it still has to compare."""
    naive = (NOW - timedelta(minutes=5)).replace(tzinfo=None)
    assert catchup_floor(naive, NOW) == NOW - timedelta(minutes=5)


@pytest.mark.parametrize(
    "detector",
    [
        "ecoguard.detectors.fire.satellite",
        "ecoguard.detectors.fire.weather",
        "ecoguard.detectors.flood.observation_processing",
        "ecoguard.detectors.earthquake.observation_processing",
        "ecoguard.detectors.air_pollution.observation_processing",
    ],
)
def test_every_scheduled_detector_bounds_its_catch_up(detector):
    """A detector reading a raw bookmark is the bug; this is what stops it coming back."""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(detector))
    assert "catchup_floor(last_success_at(" in source or "catchup_floor(bookmark" in source, (
        f"{detector} reads its bookmark without a catch-up floor"
    )
