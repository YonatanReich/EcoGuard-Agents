"""The retry storm, as a test.

On 2026-09-22 the projection table held 25 air-pollution incidents with 209
dispatch attempts between them, 205 retryable, 19 that had never once
succeeded. Each attempt was a paid model call for a plan that could not
succeed. These tests pin the two properties that stop that: a retryable
failure waits longer each time, and eventually stops being retried at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ecoguard.coordinator.dispatcher import (
    PLAN_MAX_RETRY_ATTEMPTS,
    PLAN_RETRY_BASE_MINUTES,
    plan_is_fresh,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def projection(**overrides):
    base = {
        "retryable": True,
        "attempt_count": 1,
        "last_attempt_at": NOW,
        "last_success_at": None,
    }
    base.update(overrides)
    return lambda _incident_id: base


def test_retryable_failure_is_not_retried_on_the_very_next_tick():
    """The bug: a failed plan was dispatched again ten minutes later, forever."""
    one_tick_later = NOW + timedelta(minutes=10, seconds=-1)
    assert plan_is_fresh("INC-1", one_tick_later, projection()) is True


def test_retryable_failure_is_retried_once_the_backoff_has_elapsed():
    due = NOW + timedelta(minutes=PLAN_RETRY_BASE_MINUTES)
    assert plan_is_fresh("INC-1", due, projection()) is False


def test_backoff_doubles_with_each_attempt():
    """Attempt 4 waits 8 base intervals, not one."""
    reader = projection(attempt_count=4)
    delay = PLAN_RETRY_BASE_MINUTES * 8

    assert plan_is_fresh("INC-1", NOW + timedelta(minutes=delay - 1), reader) is True
    assert plan_is_fresh("INC-1", NOW + timedelta(minutes=delay), reader) is False


def test_retries_stop_entirely_after_the_attempt_cap():
    """A plan failing structurally is not fixed by another identical call."""
    reader = projection(attempt_count=PLAN_MAX_RETRY_ATTEMPTS)
    much_later = NOW + timedelta(days=30)
    assert plan_is_fresh("INC-1", much_later, reader) is True


def test_a_recent_success_still_stands():
    reader = projection(retryable=False, last_success_at=NOW, attempt_count=3)
    assert plan_is_fresh("INC-1", NOW + timedelta(minutes=5), reader) is True


def test_an_incident_never_attempted_is_always_dispatched():
    assert plan_is_fresh("INC-1", NOW, lambda _id: None) is False


def test_a_storm_of_signals_cannot_force_extra_model_calls():
    """Signal rate must not drive model spend.

    The pollution incident behind the real burn took 208 signals over 18 hours.
    Every one touched the incident and every touch reached the dispatcher; this
    gate is the only thing between that and 208 model calls.

    The reader here mimics the real writer: upsert_event_projection increments
    attempt_count and moves last_attempt_at on every failed attempt, which is
    what makes the backoff actually widen.
    """
    state = {"retryable": True, "attempt_count": 0, "last_attempt_at": None,
             "last_success_at": None}

    now = NOW
    dispatched = 0
    # One tick every ten minutes for eighteen hours: the incident's full life.
    for _ in range(18 * 6):
        now += timedelta(minutes=10)
        if not plan_is_fresh("INC-1", now, lambda _id: dict(state)):
            dispatched += 1
            # The plan fails again, as it did 19 times in production.
            state["attempt_count"] += 1
            state["last_attempt_at"] = now

    # Previously: one call per tick for as long as signals kept arriving — 108
    # over this window. Now it is bounded by the attempt cap, whatever the
    # signal rate does.
    assert dispatched == PLAN_MAX_RETRY_ATTEMPTS


if __name__ == "__main__":
    for name, case in sorted(globals().items()):
        if name.startswith("test_") and callable(case):
            case()
            print(f"ok  {name}")
    print("\nall retry-backoff checks passed")
