"""Resuming reads the recent past once; every run after that reads only new arrivals.

The contract this pins is the whole point of the catch-up floor. Turning the
pipeline on after two days off should behave like waking up, not like replaying
the weekend - and the run straight after should be an ordinary incremental one,
with no lingering wide window.
"""

from datetime import datetime, timedelta, timezone

from ecoguard.detectors.shared.window import DEFAULT_MAX_CATCHUP, catchup_floor


def test_resuming_after_two_days_reads_the_recent_past_then_goes_incremental():
    """One wide-ish first run, then ordinary ten-minute reads."""
    windows = []

    # Detection was switched off on Tuesday; it is now Thursday.
    bookmark = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)

    # The first wave after the switch is flipped.
    since = catchup_floor(bookmark, now)
    windows.append(now - since)
    # The bookmark is the run's start time, so a successful run leaves it here.
    bookmark = now

    # The three waves after it, ten minutes apart.
    for _ in range(3):
        now = now + timedelta(minutes=10)
        since = catchup_floor(bookmark, now)
        windows.append(now - since)
        bookmark = now

    assert windows[0] == DEFAULT_MAX_CATCHUP, "the resume run reads the recent past"
    assert windows[1:] == [timedelta(minutes=10)] * 3, (
        "every run after the resume reads only what arrived since it last ran"
    )


def test_a_two_day_gap_is_never_replayed_however_long_the_pause():
    """The window does not grow with the gap, which is what stops a replay."""
    now = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
    gaps = [timedelta(hours=4), timedelta(days=2), timedelta(days=30)]

    read_back = [now - catchup_floor(now - gap, now) for gap in gaps]

    assert read_back == [DEFAULT_MAX_CATCHUP] * 3


def test_a_short_pause_is_caught_up_in_full():
    """Under the limit there is no reason to skip anything, so nothing is skipped."""
    now = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
    pause = DEFAULT_MAX_CATCHUP - timedelta(minutes=1)

    assert catchup_floor(now - pause, now) == now - pause
