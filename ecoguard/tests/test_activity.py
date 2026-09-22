"""The live-actor registry behind the System page."""

import pytest

from ecoguard.shared import activity


def test_an_actor_is_live_only_while_its_call_is_in_flight():
    seen_during = {}

    @activity.live_actor("test.actor.live")
    def work():
        seen_during.update(activity.snapshot()["test.actor.live"])
        return 42

    assert work() == 42
    assert seen_during["live"] is True

    after = activity.snapshot()["test.actor.live"]
    assert after["live"] is False
    assert after["last_outcome"] == "ok"
    assert after["last_finished_at"] is not None


def test_runs_count_every_start_so_a_missed_run_is_still_visible():
    @activity.live_actor("test.actor.runs")
    def work():
        return None

    work()
    work()
    assert activity.snapshot()["test.actor.runs"]["runs"] == 2


def test_a_failing_call_is_recorded_and_still_raises():
    @activity.live_actor("test.actor.error")
    def work():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        work()

    state = activity.snapshot()["test.actor.error"]
    assert state["live"] is False
    assert state["last_outcome"] == "error"
