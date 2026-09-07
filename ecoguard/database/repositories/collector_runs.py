"""Run accounting, so a silent collector is distinguishable from a dead one."""

from __future__ import annotations

from datetime import datetime, timezone

from ecoguard.database.engine import Session
from ecoguard.database.models import CollectorRun

# Enough of a traceback to identify the failure without letting a provider
# error message grow the row unboundedly.
MAX_ERROR_LENGTH = 2000


def log_start(source: str) -> int:
    with Session() as session:
        run = CollectorRun(
            source=source,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        session.add(run)
        session.commit()
        return run.id


def log_finish(
    run_id: int,
    *,
    status: str,
    rows_written: int | None = None,
    error: str | None = None,
) -> None:
    with Session() as session:
        run = session.get(CollectorRun, run_id)
        if run is None:
            return
        run.finished_at = datetime.now(timezone.utc)
        run.status = status
        run.rows_written = rows_written
        run.error = error[:MAX_ERROR_LENGTH] if error else None
        session.commit()
