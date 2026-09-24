"""A collector run does not become a failure because its connection died after it.

Neon closes a connection that sits idle, and `single_flight` holds one for the
whole of a collector run — through eight RSS feeds fetched over HTTP, that is a
long time. The lock is session-scoped, so Postgres has already released it by
the time the explicit unlock runs. Raising there turned a successful run into a
logged failure with a full traceback.
"""

import pytest
from sqlalchemy.exc import OperationalError

from ecoguard.database import locks


def test_a_dropped_connection_during_unlock_is_not_an_error(monkeypatch):
    """The caller's work already succeeded; the lock is already gone."""
    calls = []

    class DeadConnection:
        def execute(self, statement, params=None):
            text = str(statement)
            calls.append(text)
            if "pg_advisory_unlock" in text:
                raise OperationalError("unlock", None, Exception("server closed"))

            class Result:
                def scalar(self_inner):
                    return True

            return Result()

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(locks.engine, "connect", lambda: DeadConnection())

    with locks.single_flight("rss") as acquired:
        assert acquired is True

    assert any("pg_advisory_unlock" in call for call in calls), "unlock was attempted"


def test_a_real_failure_while_the_caller_works_still_propagates(monkeypatch):
    """Swallowing the unlock must not swallow the caller's own exception."""

    class Connection:
        def execute(self, statement, params=None):
            class Result:
                def scalar(self_inner):
                    return True

            return Result()

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(locks.engine, "connect", lambda: Connection())

    with pytest.raises(ValueError, match="the caller broke"):
        with locks.single_flight("rss"):
            raise ValueError("the caller broke")
