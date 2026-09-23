"""Whether the thinking half of the system is running.

Collection and everything downstream of it have different appetites. Collectors
are cheap, and what they miss is gone for good - a provider does not keep the
five-minute reading nobody asked for. Detection onwards costs money per event
and can be caught up at will, because it reads from the store rather than from
a provider.

So they are switched separately. Collectors run whenever the process is up;
detection, coordination, analysis and planning run only while this says so.

The reason it exists: with the model key off, every wave still marked its
incidents as failed, and six failures abandons an incident permanently. A
backend left running keyless did not merely produce nothing - it spent the
retry budget of every open incident producing nothing, and they were still
broken when the key came back.

Off by default is deliberately *not* the behaviour: a deployment that says
nothing keeps running as it always has.
"""

from __future__ import annotations

import logging
import os
import threading

from dotenv import load_dotenv

# Loaded here rather than relied on from elsewhere. This module is imported
# early and by things that touch no database, so whether `.env` had already
# been read came down to import order - and the failure was silent in the worst
# direction: ECOGUARD_PIPELINE=off was ignored and the pipeline ran.
load_dotenv()

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_OFF = {"0", "false", "no", "off"}


def _from_environment() -> bool:
    """What the environment says the pipeline should do at startup."""
    return os.getenv("ECOGUARD_PIPELINE", "on").strip().lower() not in _OFF


_enabled = _from_environment()


def is_enabled() -> bool:
    """Whether detection and everything after it may run right now."""
    with _lock:
        return _enabled


def set_enabled(enabled: bool) -> bool:
    """Turn the pipeline on or off, and report what it was changed to.

    Takes effect from the next wave. A wave already running finishes, because
    stopping one halfway would leave incidents half-processed.
    """
    global _enabled
    with _lock:
        previous, _enabled = _enabled, bool(enabled)
    if previous != _enabled:
        logger.warning(
            "pipeline %s: detection, analysis and planning are now %s",
            "enabled" if _enabled else "disabled",
            "running" if _enabled else "paused (collectors keep running)",
        )
    return _enabled
