"""Which parts of the system are running right now, for the System page.

Each detector, analyzer and planner marks itself live while it works, and the
count of past runs is kept, so a page that looked a moment too late can still
tell that a run happened.

Covers this process only."""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    """The current time, in UTC."""
    return datetime.now(timezone.utc)


@contextmanager
def active(actor: str) -> Iterator[None]:
    """Mark `actor` live for the duration of the block."""
    with _lock:
        state = _state.setdefault(actor, {
            "in_flight": 0,
            "runs": 0,
            "last_started_at": None,
            "last_finished_at": None,
            "last_outcome": None,
        })
        state["in_flight"] += 1
        state["runs"] += 1
        state["last_started_at"] = _now()

    outcome = "ok"
    try:
        yield
    except BaseException:
        outcome = "error"
        raise
    finally:
        with _lock:
            state["in_flight"] -= 1
            state["last_finished_at"] = _now()
            state["last_outcome"] = outcome


def live_actor(actor: str) -> Callable[[F], F]:
    """Decorator form of `active`, for an actor's entry point."""

    def decorate(function: F) -> F:
        """Wrap the function so it counts as live while it runs."""

        @functools.wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Mark the actor live for the length of one call."""
            with active(actor):
                return function(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate


def snapshot() -> dict[str, dict[str, Any]]:
    """Every actor that has run since the process started, as JSON-ready data."""

    def iso(value: datetime | None) -> str | None:
        """A time as text, or None when it has not happened yet."""
        return value.isoformat() if value else None

    with _lock:
        return {
            actor: {
                "live": state["in_flight"] > 0,
                "runs": state["runs"],
                "last_started_at": iso(state["last_started_at"]),
                "last_finished_at": iso(state["last_finished_at"]),
                "last_outcome": state["last_outcome"],
            }
            for actor, state in _state.items()
        }
