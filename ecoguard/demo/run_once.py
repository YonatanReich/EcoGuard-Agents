"""Run one full pipeline wave against a scenario, from the command line.

Does exactly what the scheduler does on a tick — text lane, then the five
structured detectors, the coordinator, dispatch, allocation and projection —
but once, synchronously, so a scenario can be driven and graded without
waiting ten minutes per step.

    python -m ecoguard.demo.run_once demo_a            # seed, run, grade
    python -m ecoguard.demo.run_once demo_a --no-seed  # run again on what is there

The sandbox is left populated on purpose: the whole point is to be able to show
the result afterwards.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from ecoguard.database.engine import Session, sandbox_schema, use_sandbox
from ecoguard.demo import sandbox

logger = logging.getLogger(__name__)


def run_wave() -> dict[str, int]:
    """One tick of the real pipeline. Assumes the sandbox is already entered."""
    counts: dict[str, int] = {}

    # One call: the text lane now runs inside the wave and its signals are
    # coordinated in the same batch as the structured ones.
    try:
        from ecoguard.scheduler import _detect_and_coordinate

        results = _detect_and_coordinate()
        counts["processing_results"] = len(results or [])
    except Exception:
        logger.exception("detection wave failed")
        counts["processing_results"] = -1

    with Session() as session:
        from sqlalchemy import text as sql

        for table in ("incidents", "event_projections", "text_candidates"):
            counts[table] = int(
                session.execute(sql(f"SELECT count(*) FROM {table}")).scalar_one()
            )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", default="demo_a")
    parser.add_argument("--no-seed", action="store_true",
                        help="run another wave over the existing sandbox")
    parser.add_argument("--waves", type=int, default=1,
                        help="how many ticks to run")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    from importlib import import_module

    module = import_module(f"ecoguard.demo.scenarios.{args.scenario}")
    schema = args.scenario

    if sandbox_schema() is not None:
        print(f"a sandbox is already active ({sandbox_schema()}); aborting")
        return 1

    try:
        sandbox.ensure_schema(schema)
        if not args.no_seed:
            sandbox.clear(schema)
            seeded = module.seed(schema)
            print(f"seeded {seeded['observations']} observations "
                  f"into {schema}: {seeded['by_source']}")

        use_sandbox(schema)
        started = datetime.now(timezone.utc)
        for wave in range(1, args.waves + 1):
            counts = run_wave()
            print(f"\nwave {wave} ({datetime.now(timezone.utc) - started}):")
            for key, value in counts.items():
                print(f"   {key:22} {value}")
    finally:
        use_sandbox(None)
        print("\nlive search path restored; sandbox kept for inspection")

    from ecoguard.demo.grade import main as grade_main

    return grade_main()


if __name__ == "__main__":
    sys.exit(main())
