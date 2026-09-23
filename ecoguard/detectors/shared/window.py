"""How far back a detector may look when it has been away.

Every detector reads from the bookmark its last successful run left, which is
right while it runs every ten minutes and wrong the moment it does not. After a
pause, a crash or a weekend the bookmark is days old, and reading from it means
opening incidents for fires that burned out on Tuesday.

That is not a detection: a detector answers "is something happening", and an
observation old enough to have finished happening cannot support that answer.
Whatever the gap, a detector resumes by looking at the recent past only. What
it skipped is still in the store for anything that wants to read history.

The floor only binds when the bookmark is older than it, so a detector running
on its normal interval is unaffected - a bookmark ten minutes old stays ten
minutes old. It changes the catch-up case and nothing else.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _configured_hours(default: float) -> float:
    """The catch-up limit from the environment, or the default when unset."""
    raw = os.getenv("ECOGUARD_DETECTION_MAX_CATCHUP_HOURS")
    if raw is None or not raw.strip():
        return default
    try:
        hours = float(raw)
    except ValueError:
        logger.warning(
            "ECOGUARD_DETECTION_MAX_CATCHUP_HOURS=%r is not a number; using %s",
            raw,
            default,
        )
        return default
    if hours <= 0:
        logger.warning(
            "ECOGUARD_DETECTION_MAX_CATCHUP_HOURS=%s must be positive; using %s",
            hours,
            default,
        )
        return default
    return hours


# Three hours is longer than any detector's own evidence window and shorter
# than every hazard's quiet period, so a resumed detector can still find the
# incident a reading belongs to without reaching back into finished events.
DEFAULT_MAX_CATCHUP = timedelta(hours=_configured_hours(3.0))


def catchup_floor(
    bookmark: datetime | None,
    now: datetime,
    *,
    limit: timedelta = DEFAULT_MAX_CATCHUP,
) -> datetime | None:
    """The earliest a detector should read from, given where it left off.

    Returns the bookmark when it is recent, the floor when it is not, and the
    floor when there is no bookmark at all - a detector that has never run
    should still start from the present rather than from whatever the store
    happens to hold.
    """
    floor = now - limit
    if bookmark is None:
        return floor
    if bookmark.tzinfo is None or bookmark.utcoffset() is None:
        bookmark = bookmark.replace(tzinfo=timezone.utc)
    if bookmark >= floor:
        return bookmark
    logger.warning(
        "detector bookmark %s is older than the %s catch-up limit; "
        "resuming from %s and skipping the gap",
        bookmark.isoformat(),
        limit,
        floor.isoformat(),
    )
    return floor
