"""Cross-process single-flight using Postgres advisory locks."""

from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url

from ecoguard.database.engine import DATABASE_URL, engine

logger = logging.getLogger(__name__)

if "-pooler" in (make_url(DATABASE_URL).host or ""):
    # Advisory locks are session-scoped, and a transaction pooler hands the
    # next transaction to whichever backend is free. Through the pooler a lock
    # can be taken on one backend and released on another, so single-flight
    # degrades to "usually". Use the direct endpoint: drop "-pooler" from the
    # host. The consequence is bounded — duplicate sweeps waste upstream calls
    # but the unique constraint makes their writes no-ops — so this warns
    # rather than refusing to start.
    logger.warning(
        "DATABASE_URL points at a connection pooler; collector single-flight "
        "is unreliable. Use the direct endpoint (host without '-pooler')."
    )


def lock_key(name: str) -> int:
    """Map a worker name onto the signed 64-bit integer advisory locks take."""
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


@contextmanager
def single_flight(name: str):
    """Yield True when this process took the lock, False when it is held.

    Non-blocking on purpose: a tick that cannot get the lock is skipped, not
    queued behind the run that holds it. The next tick is minutes away.

    The lock lives on the connection, so it is released by the `with` block
    even if the process is killed mid-run — Postgres drops it with the session.
    """
    key = lock_key(name)
    with engine.connect() as connection:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            ).scalar()
        )
        # End the implicit transaction that execute() opened. The lock is
        # session-scoped and survives the commit, but the connection must not
        # sit idle *in a transaction* for the length of a collector run:
        # idle_in_transaction_session_timeout is five minutes on a hosted
        # Postgres and a national weather sweep takes longer than that.
        connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                )
                connection.commit()
