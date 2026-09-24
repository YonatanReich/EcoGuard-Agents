"""Cross-process single-flight using Postgres advisory locks."""

from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

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
    """Map a worker name onto the signed 64-bit integer advisory locks take.

    Scoped to the active sandbox schema, because advisory locks belong to the
    *database* and a scenario shares one with the live pipeline. Unscoped, a
    scenario's coordinator run silently lost the `coordinate_coordinator` lock
    to whichever live wave happened to be mid-tick, skipped coordination, and
    produced no incidents — with no failed row anywhere to say why, since
    `single_flight` returning False is a normal outcome and not an error.

    A scenario that cannot coordinate is worse than one that fails loudly: it
    grades as "the system detected nothing".
    """
    from ecoguard.database.engine import sandbox_schema

    schema = sandbox_schema()
    scoped = f"{schema}:{name}" if schema else name
    digest = hashlib.blake2b(scoped.encode("utf-8"), digest_size=8).digest()
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
                try:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                    )
                    connection.commit()
                except OperationalError:
                    # The connection died while the caller was working, which a
                    # serverless Postgres does to one sitting idle through a
                    # long run. Releasing the lock is exactly what Postgres has
                    # already done by ending the session, so there is nothing
                    # to recover from and nothing a caller could do about it.
                    # Raising here turned a successful collector run into a
                    # logged failure with a full traceback.
                    logger.info(
                        "%s: connection closed before the lock was released; "
                        "Postgres released it with the session",
                        name,
                    )
