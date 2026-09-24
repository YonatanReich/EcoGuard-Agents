"""Pointing the whole pipeline at a demo dataset instead of live data.

Swaps the database schema the detectors read from, so everything downstream
runs unchanged and unaware. Live collection is paused while a demo runs, and
resumed when it ends.

The demo data is kept, not dropped, so the same scenario can be shown again."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session, engine, sandbox_schema, use_sandbox

logger = logging.getLogger(__name__)

# The tables a pipeline run writes to, and the observations it reads. Anything
# not listed here resolves to `public` through the search path, which is how a
# sandbox incident still finds the real town, police station and baseline it
# should be reasoned about against.
#
# collector_runs is the non-obvious one and the most important: it holds every
# detector's bookmark. Left in `public`, a scenario would start from the live
# bookmarks, decide the seeded observations were already processed, and detect
# nothing at all.
SANDBOXED_TABLES = (
    "observations",
    "collector_runs",
    "incidents",
    "event_projections",
    "text_candidates",
    "resource_allocations",
    "weak_events",
)


def ensure_schema(schema: str) -> list[str]:
    """Create the sandbox schema and its tables if they are not already there.

    Idempotent, so the button works on a fresh database and on the twentieth
    run. `LIKE ... INCLUDING ALL` copies columns, types, defaults, indexes and
    check constraints but *not* foreign keys, which is what we want: a sandbox
    observation must not have to satisfy a reference to a public row.
    """
    created = []
    with Session() as session:
        session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        for table in SANDBOXED_TABLES:
            exists = session.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": schema, "table": table},
            ).first()
            if exists:
                continue
            session.execute(
                text(
                    f'CREATE TABLE "{schema}"."{table}" '
                    f"(LIKE public.\"{table}\" INCLUDING ALL)"
                )
            )
            _restore_constraint_names(session, schema, table)
            created.append(table)
        session.commit()
    if created:
        logger.info("sandbox %s: created %s", schema, ", ".join(created))
    return created


def _restore_constraint_names(session, schema: str, table: str) -> None:
    """Give the copied constraints the names the application writes in SQL.

    `LIKE ... INCLUDING ALL` copies a unique constraint's *definition* but
    regenerates its *name* from the column list, so `text_candidates_identity`
    arrives as `text_candidates_observation_id_hazard_key`. Application code
    that says `ON CONFLICT ON CONSTRAINT text_candidates_identity` then fails
    against the sandbox and only the sandbox — a difference between the two
    worlds, which is the one thing a harness like this must not have.

    Matching is by definition rather than by name, since the name is precisely
    what differs. Names are unique per schema, so reusing public's is safe.
    """
    originals = session.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint WHERE conrelid = ('public.' || :table)::regclass"
        ),
        {"table": table},
    ).mappings().all()
    copies = session.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint "
            "WHERE conrelid = (:schema || '.' || :table)::regclass"
        ),
        {"schema": schema, "table": table},
    ).mappings().all()

    copied_names = {row["conname"] for row in copies}
    by_definition = {
        row["definition"]: row["conname"]
        for row in copies
        if row["conname"] not in {item["conname"] for item in originals}
    }

    for original in originals:
        if original["conname"] in copied_names:
            continue
        current = by_definition.get(original["definition"])
        if current is None:
            # Foreign keys are deliberately not copied by LIKE, and a sandbox
            # row must not have to satisfy a reference into `public`.
            continue
        session.execute(
            text(
                f'ALTER TABLE "{schema}"."{table}" '
                f'RENAME CONSTRAINT "{current}" TO "{original["conname"]}"'
            )
        )
        logger.info(
            "sandbox %s.%s: renamed %s -> %s",
            schema, table, current, original["conname"],
        )


def clear(schema: str) -> None:
    """Empty every sandbox table, so a run starts from a known blank world."""
    quoted = ", ".join(f'"{schema}"."{table}"' for table in SANDBOXED_TABLES)
    with Session() as session:
        # RESTART IDENTITY keeps ids small and predictable across runs, which
        # matters when reading the output by eye afterwards.
        session.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY"))
        session.commit()
    logger.info("sandbox %s: cleared", schema)


def counts(schema: str) -> dict[str, int]:
    """Row counts per sandbox table, for the status endpoint and for grading."""
    result: dict[str, int] = {}
    with Session() as session:
        for table in SANDBOXED_TABLES:
            try:
                result[table] = int(
                    session.execute(
                        text(f'SELECT count(*) FROM "{schema}"."{table}"')
                    ).scalar_one()
                )
            except Exception:
                result[table] = -1
    return result


def drop(schema: str) -> None:
    """Remove the sandbox entirely. Never touches `public`."""
    if schema == "public":
        raise ValueError("refusing to drop public")
    with Session() as session:
        session.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        session.commit()
    logger.warning("sandbox %s: dropped", schema)


# --------------------------------------------------------------------------
# Collector control
# --------------------------------------------------------------------------
#
# Collectors must not run during a scenario. They would fetch live FIRMS,
# weather and pollution data and write it into whichever schema is on the
# search path — putting real observations inside the controlled world, where an
# unexpected genuine fire would be indistinguishable from a seeded one when the
# results are graded.
#
# The detection wave keeps running: that is the thing under test.
COLLECTOR_JOB_PREFIX = "collect_"
WAVE_JOB_ID = "detect_and_coordinate"


def _scheduler():
    """The running scheduler, imported late so this module can be used without one."""
    from ecoguard.scheduler import scheduler

    return scheduler


def pause_collectors() -> list[str]:
    """Pause every collector job, leaving the detection wave running."""
    paused = []
    try:
        scheduler = _scheduler()
        for job in scheduler.get_jobs():
            if job.id.startswith(COLLECTOR_JOB_PREFIX) or job.id == "prune_observations":
                job.pause()
                paused.append(job.id)
    except Exception:
        # A scenario is still worth running without the scheduler — the wave
        # can be stepped by hand — so this reports rather than fails.
        logger.exception("could not pause collectors")
    return paused


def resume_collectors() -> list[str]:
    """Resume everything pause_collectors stopped."""
    resumed = []
    try:
        scheduler = _scheduler()
        for job in scheduler.get_jobs():
            if job.id.startswith(COLLECTOR_JOB_PREFIX) or job.id == "prune_observations":
                job.resume()
                resumed.append(job.id)
    except Exception:
        logger.exception("could not resume collectors")
    return resumed


# --------------------------------------------------------------------------
# Run lifecycle
# --------------------------------------------------------------------------

_started_at: datetime | None = None
_scenario_name: str | None = None
_expectations: dict[str, Any] | None = None


_wave_thread: "threading.Thread | None" = None


def kick_wave() -> bool:
    """Run one detection wave now, in the background.

    The scheduler would get there on its own within ten minutes, but a demo
    that shows nothing for ten minutes after the button is pressed is not a
    demo. Returns False when a wave this process started is still running —
    the wave also holds a database lock, so a second one would skip anyway.

    Daemon thread: a wave in flight must never keep the API process alive on
    shutdown, and the work is resumable by the next tick either way.
    """
    global _wave_thread

    if _wave_thread is not None and _wave_thread.is_alive():
        logger.info("scenario: a wave is already running, not starting another")
        return False

    def run() -> None:
        """Run one detection tick against the sandbox.

        Forced past the pipeline switch on purpose. Somebody pressed a button
        asking for this, which is a different thing from a timer firing on its
        own, and the switch is there to stop the latter.
        """
        try:
            from ecoguard.scheduler import detect_and_coordinate

            detect_and_coordinate(force=True)
        except Exception:
            logger.exception("scenario wave failed")

    _wave_thread = threading.Thread(
        target=run, name="scenario-wave", daemon=True
    )
    _wave_thread.start()
    return True


def wave_running() -> bool:
    """Whether the wave this process kicked is still going."""
    return _wave_thread is not None and _wave_thread.is_alive()


_stopping = False


def stopping() -> bool:
    """Whether a stop is queued behind a wave that has not finished."""
    return _stopping


def _schedule_stop(*, keep_data: bool) -> None:
    """Wait for the running wave, then restore the live tables."""
    global _stopping

    if _stopping:
        return
    _stopping = True
    waiting_for = _wave_thread

    def watcher() -> None:
        """Wait for the demo to finish, then put everything back."""
        global _stopping
        try:
            if waiting_for is not None:
                waiting_for.join()
            stop(keep_data=keep_data)
        except Exception:
            logger.exception("deferred scenario stop failed")
        finally:
            _stopping = False

    threading.Thread(
        target=watcher, name="scenario-stop", daemon=True
    ).start()
    logger.warning("scenario stop queued behind the running wave")


def status() -> dict[str, Any]:
    """What the scenario controller is doing, for the dashboard banner."""
    schema = sandbox_schema()
    return {
        "running": schema is not None,
        "schema": schema,
        "scenario": _scenario_name,
        "started_at": _started_at.isoformat() if _started_at else None,
        "counts": counts(schema) if schema else {},
        "wave_running": wave_running(),
        "stopping": stopping(),
        "expectations": _expectations,
    }


def start(scenario: str, *, seeder, schema: str | None = None) -> dict[str, Any]:
    """Enter the sandbox, clear it, seed it, and stop the collectors.

    The order matters. The schema is prepared and seeded *while still pointed
    at the live tables* — the seeder writes with an explicit schema — and the
    search path is switched last, so a half-built world is never the one the
    detection wave sees.
    """
    global _started_at, _scenario_name, _expectations

    if sandbox_schema() is not None:
        raise RuntimeError(f"scenario {_scenario_name!r} is already running")

    # The scenario name is the schema name: "demo_a" -> schema demo_a. The
    # endpoint validates the name against SCENARIOS before it gets here.
    target = schema or scenario
    ensure_schema(target)
    clear(target)
    seeded = seeder(target)

    paused = pause_collectors()
    use_sandbox(target)

    _started_at = datetime.now(timezone.utc)
    _scenario_name = scenario
    _expectations = seeded.get("expectations")

    # The detectors wake on the seeded table straight away rather than at the
    # next ten-minute tick.
    kick_wave()

    logger.warning(
        "scenario %s started in schema %s: %s observations seeded, %s collectors paused",
        scenario, target, seeded.get("observations", 0), len(paused),
    )
    return {
        "scenario": scenario,
        "schema": target,
        "seeded": seeded,
        "collectors_paused": paused,
        "started_at": _started_at.isoformat(),
    }


def stop(*, keep_data: bool = True) -> dict[str, Any]:
    """Return to the live tables and restart the collectors.

    The sandbox rows are kept by default so the run can be graded after it
    ends. Nothing in them can reach the live dashboard once the search path is
    back on `public`.
    """
    global _started_at, _scenario_name, _expectations

    schema = sandbox_schema()
    if schema is None:
        return {"running": False, "note": "no scenario was running"}

    # Never switch the search path out from under a wave that is still running.
    #
    # `use_sandbox` disposes the pool, so a wave mid-flight would finish its
    # remaining writes — incidents, projections, classified candidates — against
    # `public`. That is scenario data landing in the live store, which is the
    # one thing this whole design exists to prevent. Observed: ending a demo
    # seconds after starting it put the classifier's insert on the live tables.
    #
    # So a stop requested during a wave is *scheduled* rather than performed.
    # The caller returns immediately, `status()` reports `stopping`, and a
    # watcher flips back the moment the wave ends.
    if wave_running():
        _schedule_stop(keep_data=keep_data)
        return {
            "running": True,
            "stopping": True,
            "scenario": _scenario_name,
            "schema": schema,
            "note": (
                "a detection wave is still running; the live tables are "
                "restored as soon as it finishes"
            ),
        }

    final = counts(schema)
    use_sandbox(None)
    resumed = resume_collectors()

    if not keep_data:
        clear(schema)

    finished = {
        "scenario": _scenario_name,
        "schema": schema,
        "ran_from": _started_at.isoformat() if _started_at else None,
        "ran_to": datetime.now(timezone.utc).isoformat(),
        "final_counts": final,
        "collectors_resumed": resumed,
        "data_kept": keep_data,
    }
    logger.warning("scenario %s stopped; live tables restored", _scenario_name)
    _started_at = _scenario_name = _expectations = None
    return finished


__all__ = [
    "SANDBOXED_TABLES",
    "clear",
    "counts",
    "drop",
    "ensure_schema",
    "start",
    "status",
    "stop",
]
