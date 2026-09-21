"""How long each source is kept, and why it is that long.

The table only grows, and at current cadence it grows by about 8.6 GB a year —
weather and weather_forecast between them are 96% of that. Something has to
bound it. Clearing the whole table on a timer is the obvious move and the wrong
one: five things read further back than a day, and three of them break in ways
no later collection can repair.

The rule that decides every number below is **prune what can be re-fetched,
keep what cannot**:

  * Weather is re-fetchable. Open-Meteo's archive serves historical hours back
    to 1940, free, so stored weather is a cache of something still available.
    Ninety days is a season of context; anything older can be fetched again if
    a question ever needs it.
  * A forecast is *not* re-fetchable — nobody serves last week's model runs —
    but it is superseded every six hours and its lasting value is forecast
    skill, which thirty days of runs measures perfectly well.
  * The FWI chain is not re-fetchable at all, because it is not fetched: it is
    our own accumulator, and each day's row is computed from the one before it.
    Deleting it destroys months of drought memory that no amount of later
    collection rebuilds. It is also only 0.2 GB a year. It is never pruned.
  * FIRMS is never pruned because the fire-history features are defined over
    365 days and the persistent-hotspot filter needs 60 — and because at a few
    dozen rows a day it costs nothing.
  * Telegram is never pruned because the collector deliberately stores raw
    unclassified text so old messages can be re-read when the extractor
    improves. Upstream messages get edited and deleted; this is the only copy.

Steady state under this policy is roughly 1.6 GB rather than unbounded growth.

Deletes here are small and routine, so ordinary autovacuum reclaims the space
for reuse. If the volumes ever grow enough that this stops being true, the
answer is range partitioning on observed_at — `observed_at` is already part of
the identity constraint, so partitioning is available without a schema
redesign, and dropping a partition is instant where a DELETE is not.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.database.repositories.collector_runs import log_finish, log_start

logger = logging.getLogger(__name__)

SOURCE = "retention"

# None means never prune. See the module docstring for the reasoning behind
# each number; they are not a uniform policy and should not be made into one.
RETENTION_DAYS: dict[str, int | None] = {
    "weather": 90,
    "weather_forecast": 30,
    "fire_weather": 400,
    "vegetation": 400,
    "water_authority_hydrometric_observations": 30,
    "fwi": None,
    "firms": None,
    "telegram": None,
}


def prune(dry_run: bool = False) -> dict[str, int]:
    """Delete observations past their source's retention, oldest first.

    Args:
        dry_run: count what would be deleted without deleting it. Worth using
            the first time a policy changes — the counts are the only warning
            that a number was set wrong.

    Returns:
        dict: source to rows removed (or removable, when dry_run). Sources with
            no retention are absent rather than reported as zero, so "kept
            forever" never reads as "nothing to do today".

    A source absent from RETENTION_DAYS is left alone and warned about, not
    pruned by a default. A new collector should have its retention decided
    deliberately, and silently applying someone else's number to it is how the
    FWI chain would eventually get deleted by a policy that never considered it.
    """
    removed: dict[str, int] = {}

    with Session() as session:
        present = set(
            session.execute(text("SELECT DISTINCT source FROM observations")).scalars().all()
        )
        for source in sorted(present - set(RETENTION_DAYS)):
            logger.warning(
                "retention: %r has no policy and was left untouched; add it to RETENTION_DAYS",
                source,
            )

        for source, days in RETENTION_DAYS.items():
            if days is None:
                continue
            statement = (
                "SELECT count(*) FROM observations"
                if dry_run
                else "DELETE FROM observations"
            )
            result = session.execute(
                text(
                    f"""
                    {statement}
                    WHERE source = :source
                      AND observed_at < now() - make_interval(days => :days)
                    """
                ),
                {"source": source, "days": days},
            )
            count = result.scalar_one() if dry_run else result.rowcount
            if count:
                removed[source] = count
        if not dry_run:
            session.commit()

    return removed


def run(dry_run: bool = False) -> None:
    """Prune once, recording the outcome like any other scheduled job.

    Never raises, for the same reason the collectors do not: a failed prune is
    a table that is larger than intended, which is survivable, where a raised
    exception out of a scheduler thread is not.
    """
    run_id = log_start(SOURCE)
    try:
        removed = prune(dry_run=dry_run)
        total = sum(removed.values())
        log_finish(run_id, status="ok", rows_written=total)
        logger.info(
            "retention: %s rows %s (%s)",
            f"{total:,}",
            "removable" if dry_run else "removed",
            ", ".join(f"{source} {count:,}" for source, count in removed.items()) or "nothing due",
        )
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        logger.exception("retention failed")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be deleted without deleting it",
    )
    arguments = parser.parse_args()

    removed = prune(dry_run=arguments.dry_run)
    verb = "would remove" if arguments.dry_run else "removed"
    for source, days in RETENTION_DAYS.items():
        if days is None:
            print(f"  {source:18s} kept forever")
        else:
            print(f"  {source:18s} {days:>4}d   {verb} {removed.get(source, 0):,}")


if __name__ == "__main__":
    main()
