"""Cross-process single-flight using Postgres advisory locks."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

from sqlalchemy import text

from ecoguard.database.engine import engine


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
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                )
