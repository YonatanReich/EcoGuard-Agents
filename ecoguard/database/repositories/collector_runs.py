"""Run accounting, so a silent collector is distinguishable from a dead one."""

from __future__ import annotations

from datetime import datetime, timezone

from ecoguard.database.engine import Session
from ecoguard.database.models import CollectorRun

# Enough of a traceback to identify the failure without letting a provider
# error message grow the row unboundedly.
MAX_ERROR_LENGTH = 2000


def log_start(source: str) -> int:
    """Record that a collector has begun, and return the run to close later."""
    with Session() as session:
        run = CollectorRun(
            source=source,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        session.add(run)
        session.commit()
        return run.id


def last_success_at(source: str) -> datetime | None:
    """When this source last completed a run successfully, or None if never.

    This doubles as a detector's bookmark. A detector has to process what
    arrived while it was asleep, not what happens to fall inside a fixed window
    — a window silently drops everything older than itself, so a detector that
    was down for longer than its window never sees those rows at all and logs
    nothing about it.

    Deliberately the *start* of the run rather than its finish. Rows ingested
    between this timestamp and the moment the run actually read are picked up
    twice: once by that run, once by the next. Duplicates are absorbed by the
    coordinator, which exists for precisely that; a gap would be a fire nobody
    ever sees. At-least-once is the only acceptable direction here.

    Failed runs are ignored, so a crash re-reads its span instead of skipping it.
    """
    from sqlalchemy import select

    with Session() as session:
        return session.execute(
            select(CollectorRun.started_at)
            .where(CollectorRun.source == source, CollectorRun.status == "ok")
            .order_by(CollectorRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()


def log_finish(
    run_id: int,
    *,
    status: str,
    rows_written: int | None = None,
    error: str | None = None,
) -> None:
    """Record how a collector run ended and what it wrote."""
    with Session() as session:
        run = session.get(CollectorRun, run_id)
        if run is None:
            return
        run.finished_at = datetime.now(timezone.utc)
        run.status = status
        run.rows_written = rows_written
        run.error = error[:MAX_ERROR_LENGTH] if error else None
        session.commit()
