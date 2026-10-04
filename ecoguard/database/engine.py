"""The database connection, opened once when the process starts.

Reading the connection string at startup means a missing or malformed one fails
immediately, rather than surfacing much later as a failed collector run.

Also owns the sandbox switch: pointing every query at a demo schema instead of
the live one, which is what lets a demo run through the real pipeline without
touching real data."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
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

_TRANSACTION_POOLER = "-pooler" in (make_url(DATABASE_URL).host or "")

# create_engine does not connect, so an unreachable host is discovered on first
# use. pool_pre_ping discards connections a hosted Postgres has already closed,
# which a worker sleeping thirty minutes between ticks will meet constantly.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)

# The collectors get their own engine on the same database, and it never leaves
# `public`. Sharing one engine with the pipeline is what let a demo contaminate
# the live store in both directions:
#
#   * A collector already running when a scenario started kept going, and its
#     next connection came from the freshly disposed pool carrying
#     `demo_b, public`. It wrote five real earthquakes into `demo_b`.
#     `job.pause()` does not stop a job that is already executing, so pausing
#     the scheduler narrows the window without closing it.
#   * That collector's run record was opened in `demo_b` and closed after the
#     scenario ended, against `public` — leaving a row stuck at `running` in a
#     schema, and a matching orphan in the other.
#
# Two pools make the timing irrelevant: a collector's connection cannot carry a
# sandbox search path, whatever is happening in the pipeline when it runs.
collector_engine = create_engine(
    DATABASE_URL, pool_pre_ping=True, pool_recycle=1800
)

_PipelineSession = sessionmaker(bind=engine, expire_on_commit=False)
_CollectorSession = sessionmaker(bind=collector_engine, expire_on_commit=False)

# A ContextVar rather than a module flag: a collector and a scenario wave run in
# different scheduler threads at the same time, and a global would have one
# deciding the other's destination.
_collector_context: ContextVar[bool] = ContextVar(
    "ecoguard_collector_database", default=False
)


@contextmanager
def collector_database() -> Iterator[None]:
    """Route every session opened in this context at the live tables.

    Wraps a collector's whole run - lock, run records, reads and writes - not
    just its final insert, because a collector reads before it writes and a
    read against the wrong schema is how a demo's authored rows get treated as
    live ones.
    """
    token = _collector_context.set(True)
    try:
        yield
    finally:
        _collector_context.reset(token)


def is_collector_context() -> bool:
    """Whether the caller is inside `collector_database`."""
    return _collector_context.get()


class _SessionRouter:
    """Hands out a session bound to whichever engine the caller belongs to.

    Exists so the hundred-odd `with Session() as session:` call sites did not
    each need to learn about the split.
    """

    @staticmethod
    def _maker():
        """The session factory for the current context."""
        return _CollectorSession if _collector_context.get() else _PipelineSession

    def __call__(self, **kwargs):
        """Open a session on the right engine."""
        return self._maker()(**kwargs)

    def begin(self, **kwargs):
        """Open a session already in a transaction, on the right engine."""
        return self._maker().begin(**kwargs)


Session = _SessionRouter()


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
    #
    # Only the pipeline pool. `collector_engine` is deliberately untouched:
    # collectors stay on `public` through a scenario, which is the whole point
    # of it being a separate pool.
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
    # A transaction pooler can hand the next transaction to a different
    # PostgreSQL backend, so session state set here is not a routing guarantee.
    # The begin listeners below use SET LOCAL for that deployment shape.
    if _TRANSACTION_POOLER:
        return

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


@event.listens_for(collector_engine, "connect")
def _pin_collector_to_public(dbapi_connection, connection_record):
    """Hold every collector connection on `public`, whatever the pipeline is doing.

    Same autocommit dance as the pipeline listener above, and for the same
    reason: `SET` is transactional, so a statement issued inside the implicit
    transaction is undone when SQLAlchemy rolls the connection back into the
    pool. Stated explicitly rather than relying on the server default, because
    the default is what a future `ALTER ROLE ... SET search_path` would change
    without anyone connecting this file to the consequence.
    """
    if _TRANSACTION_POOLER:
        return

    previous = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET search_path TO public")
        finally:
            cursor.close()
    finally:
        dbapi_connection.autocommit = previous


if _TRANSACTION_POOLER:
    # PgBouncer-style transaction pooling does not preserve session settings
    # between transactions. SET LOCAL is tied to the transaction itself, so
    # every statement in that unit of work sees one deterministic world even
    # when the proxy assigns a different backend on the next checkout.
    @event.listens_for(engine, "begin")
    def _apply_transaction_search_path(connection):
        wanted = f'"{_sandbox_schema}", public' if _sandbox_schema else "public"
        connection.exec_driver_sql(f"SET LOCAL search_path TO {wanted}")

    @event.listens_for(collector_engine, "begin")
    def _pin_collector_transaction_to_public(connection):
        connection.exec_driver_sql("SET LOCAL search_path TO public")
