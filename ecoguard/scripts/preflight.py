"""Is this machine ready to run the system?

Checks the settings, the database, and whether each collector has run recently,
and reports anything that would stop a demo before it starts rather than in
front of an audience."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

OK, WARN, FAIL = "ok", "warn", "FAIL"

# How stale a source may be before it is worth mentioning. Each is a few times
# its collection interval, so a single missed tick is not an alarm. Sources
# that publish rarely by nature (a lake level, an 8-day vegetation composite)
# get long allowances rather than being left out, because "nothing since the
# 16th" is still worth seeing before a demo.
STALENESS_BUDGET = {
    "air_pollution": timedelta(minutes=30),
    "firms": timedelta(hours=3),
    "weather": timedelta(hours=4),
    "rss": timedelta(minutes=30),
    "telegram": timedelta(minutes=30),
    "water_authority_hydrometric_observations": timedelta(hours=1),
    "gsi_earthquake": timedelta(minutes=30),
    "fire_weather": timedelta(hours=12),
    "fwi": timedelta(hours=12),
    "weather_forecast": timedelta(hours=12),
    "vegetation": timedelta(hours=24),
    "kinneret_level": timedelta(days=7),
}

# Without these the demo is missing a visible feature, so they are checked by
# name rather than discovered on first failure.
REQUIRED_ENV = ("DATABASE_URL", "ANTHROPIC_API_KEY")
OPTIONAL_ENV = ("NASA_FIRMS_API_KEY", "TELEGRAM_API_ID", "TELEGRAM_API_HASH")

results: list[tuple[str, str, str]] = []


def record(status: str, check: str, detail: str) -> None:
    """Note the result of one check."""
    results.append((status, check, detail))


def check_environment() -> None:
    """Whether every required setting and key is present."""
    for name in REQUIRED_ENV:
        present = bool((os.getenv(name) or "").strip())
        record(OK if present else FAIL, name, "set" if present else "not set or empty")
    for name in OPTIONAL_ENV:
        present = bool((os.getenv(name) or "").strip())
        record(
            OK if present else WARN,
            name,
            "set" if present else "not set or empty - that lane is skipped entirely",
        )


def check_database() -> bool:
    """Whether the database is reachable and up to date."""
    try:
        from sqlalchemy import text

        from ecoguard.database.engine import engine

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        record(FAIL, "database", f"unreachable: {type(error).__name__}")
        return False
    record(OK, "database", "reachable")
    return True


def check_claude() -> None:
    """Four tokens, and the one failure that silently kills every model lane."""
    try:
        from ecoguard.shared.llm import probe_model_reachability

        kind = probe_model_reachability()
    except Exception as error:
        record(FAIL, "claude", f"probe raised {type(error).__name__}")
        return
    if kind == "ok":
        record(OK, "claude", "reachable")
    elif kind == "insufficient credit":
        record(FAIL, "claude", "OUT OF CREDIT - every planner will fail silently")
    else:
        record(FAIL, "claude", kind)


def check_wave_lock() -> None:
    """A held lock means another backend is already running against this database."""
    try:
        from ecoguard.database.locks import single_flight

        with single_flight("detect_and_coordinate") as acquired:
            if acquired:
                record(OK, "wave lock", "free - no other backend on this database")
            else:
                record(
                    FAIL,
                    "wave lock",
                    "HELD by another process - stop it, or every model call is paid twice",
                )
    except Exception as error:
        record(WARN, "wave lock", f"could not test: {type(error).__name__}")


def check_collectors() -> None:
    """Whether each collector has run recently enough."""
    try:
        from sqlalchemy import text

        from ecoguard.database.engine import engine

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT source,
                           max(started_at) FILTER (WHERE status = 'ok') AS last_ok
                      FROM collector_runs
                     GROUP BY source
                    """
                )
            ).mappings().all()
    except Exception as error:
        record(WARN, "collectors", f"could not read collector_runs: {type(error).__name__}")
        return

    seen = {row["source"]: row["last_ok"] for row in rows}
    now = datetime.now(timezone.utc)

    for source, budget in sorted(STALENESS_BUDGET.items()):
        last_ok = seen.get(source)
        if last_ok is None:
            record(WARN, f"collector {source}", "has never succeeded")
            continue
        age = now - last_ok
        if age > budget:
            record(
                WARN,
                f"collector {source}",
                f"last success {_age(age)} ago, budget {_age(budget)}",
            )
        else:
            record(OK, f"collector {source}", f"fresh ({_age(age)} ago)")


def _age(delta: timedelta) -> str:
    """How long ago something happened, in words."""
    minutes = int(delta.total_seconds() // 60)
    if minutes < 90:
        return f"{minutes}m"
    hours = minutes / 60
    return f"{hours:.0f}h" if hours < 48 else f"{hours / 24:.1f}d"


def main() -> int:
    """Run every readiness check and report what would stop a demo."""
    check_environment()
    if check_database():
        check_wave_lock()
        check_collectors()
    check_claude()

    width = max(len(check) for _, check, _ in results)
    for status, check, detail in results:
        marker = {OK: "  ok ", WARN: " warn", FAIL: " FAIL"}[status]
        print(f"{marker}  {check.ljust(width)}  {detail}")

    failures = sum(1 for status, _, _ in results if status == FAIL)
    warnings = sum(1 for status, _, _ in results if status == WARN)
    print(
        f"\n{failures} failure(s), {warnings} warning(s). "
        + ("Ready to demo." if failures == 0 else "Fix the failures before demoing.")
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
