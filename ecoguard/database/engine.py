"""The database connection, opened once when the process starts.

Reading the connection string at startup means a missing or malformed one fails
immediately, rather than surfacing much later as a failed collector run.

Also owns the sandbox switch: pointing every query at a demo schema instead of
the live one, which is what lets a demo run through the real pipeline without
touching real data."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to .env, for example "
        "postgresql+psycopg://user:password@host/dbname?sslmode=require "
        "(see .env.example)."
    )

# create_engine does not connect, so an unreachable host is discovered on first
# use. pool_pre_ping discards connections a hosted Postgres has already closed,
# which a worker sleeping thirty minutes between ticks will meet constantly.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)

Session = sessionmaker(bind=engine, expire_on_commit=False)


# --------------------------------------------------------------------------
# Demo sandbox
# --------------------------------------------------------------------------
#
# A scenario run needs the whole pipeline to read hand-authored observations
# instead of the real ones, and to write its incidents somewhere that is not
# the live store. Every query in this project names tables unqualified —
# `FROM observations`, never `FROM public.observations` — so a schema on the
# search path in front of `public` redirects all of them at once, with no
# query, repository or detector change anywhere.
#
# Only the *mutable* pipeline tables are created in the sandbox schema. The
# reference data an analyser needs — towns, police and fire stations, the
# surface grid, pollution and weather baselines, the protocol corpus — is left
# out on purpose, so those lookups fall through to `public` and the sandbox
# reasons about the real country. That fall-through is the whole reason this is
# a schema rather than a separate database: copying 1,168 towns and every
# baseline into a second database is how a demo environment silently drifts
# from the real one.
#
# Process-wide state, deliberately: the scheduler, the API request handlers and
# the detection wave all have to agree on which world they are in, and they
# share a process by design (see the Dockerfile's one-worker rule).
_sandbox_schema: str | None = None


def sandbox_schema() -> str | None:
    """Which sandbox schema is active, or None for the live tables."""
    return _sandbox_schema


def use_sandbox(schema: str | None) -> None:
    """Point every later session at a sandbox schema, or back at `public`.

    Takes effect on the next connection checkout rather than immediately, so a
    session already in flight finishes against the world it started in.
    """
    global _sandbox_schema
    if schema is not None and not schema.replace("_", "").isalnum():
        # Interpolated into SQL below, so it is validated rather than escaped.
        raise ValueError(f"unsafe schema name: {schema!r}")
    _sandbox_schema = schema
    logger.warning(
        "database search_path now %s",
        f"{schema}, public (SANDBOX)" if schema else "public (live)",
    )
    # Existing pooled connections still carry the old search_path, and the
    # listener below only fires on checkout. Disposing the pool is the blunt
    # way to guarantee nothing keeps writing to the world we just left.
    engine.dispose()


@event.listens_for(engine, "connect")
def _apply_search_path(dbapi_connection, connection_record):
    """Set the search path on every real connection, as it is opened.

    On `connect` rather than `checkout`, and with no caching, because both of
    the obvious alternatives are wrong:

    * Caching the applied value on `connection_record.info` looks like an easy
      win and silently breaks. `pool_pre_ping` and `pool_recycle` replace the
      underlying DBAPI connection while keeping the same record, so the cache
      says "already set" over a brand-new connection that still has the server
      default. The symptom is a sandbox that isolates intermittently — the
      worst possible failure for a harness whose whole job is to be trusted.
    * Setting it unconditionally on every checkout is correct but pays a round
      trip per checkout, and this database is ~150 ms away.

    `connect` fires exactly once per real connection, including on the silent
    reconnects above, so it is both free and reconnect-proof. `use_sandbox`
    disposes the pool, so every connection after a mode switch is a new one and
    passes through here.

    The autocommit dance is not optional, and it is the subtler half of the
    bug. `SET` is transactional in Postgres, and SQLAlchemy rolls a connection
    back when it returns to the pool — so a `SET search_path` issued inside the
    implicit transaction is silently undone the moment the first session
    finishes with it. The observable symptom was a sandbox that isolated on the
    first query of a connection and leaked on every reuse, alternating as the
    pool handed connections round. Run outside a transaction, the statement
    changes the session default and survives every later rollback.
    """
    wanted = f'"{_sandbox_schema}", public' if _sandbox_schema else "public"
    previous = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET search_path TO {wanted}")
        finally:
            cursor.close()
    finally:
        dbapi_connection.autocommit = previous
