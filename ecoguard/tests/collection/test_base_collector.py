"""run() is the collection layer's only real guarantee: it must never raise."""

import pytest

from ecoguard.collection import base
from ecoguard.collection.base import BaseCollector


class _Recorder:
    def __init__(self, monkeypatch, *, acquired=True):
        self.finished = []
        self.upserted = None

        from contextlib import contextmanager

        @contextmanager
        def single_flight(name):
            self.lock_name = name
            yield acquired

        monkeypatch.setattr(base, "single_flight", single_flight)
        monkeypatch.setattr(base, "log_start", lambda source: 7)
        monkeypatch.setattr(
            base, "log_finish",
            lambda run_id, **kwargs: self.finished.append((run_id, kwargs)),
        )

        def upsert(source, records):
            self.upserted = (source, list(records))
            return len(self.upserted[1])

        monkeypatch.setattr(base, "upsert_observations", upsert)


class _Exploding(BaseCollector):
    source = "boom"

    def fetch(self):
        raise RuntimeError("provider is down")


class _Working(BaseCollector):
    source = "fine"

    def fetch(self):
        return [{"cell_id": "c1", "observed_at": None, "payload": {}}]


def test_failing_fetch_returns_normally_and_writes_a_failed_run(monkeypatch):
    recorder = _Recorder(monkeypatch)

    _Exploding().run()  # must not raise

    assert len(recorder.finished) == 1
    run_id, fields = recorder.finished[0]
    assert run_id == 7
    assert fields["status"] == "failed"
    assert "provider is down" in fields["error"]


def test_successful_run_reports_the_rows_it_wrote(monkeypatch):
    recorder = _Recorder(monkeypatch)

    _Working().run()

    assert recorder.upserted[0] == "fine"
    assert recorder.finished == [(7, {"status": "ok", "rows_written": 1})]


def test_held_lock_skips_the_tick_without_starting_a_run(monkeypatch):
    recorder = _Recorder(monkeypatch, acquired=False)

    _Working().run()

    assert recorder.lock_name == "collect_fine"
    assert recorder.finished == []
    assert recorder.upserted is None


def test_unreachable_database_does_not_stop_the_scheduler(monkeypatch):
    def exploding_single_flight(name):
        raise OSError("connection refused")

    monkeypatch.setattr(base, "single_flight", exploding_single_flight)

    _Working().run()  # must not raise
