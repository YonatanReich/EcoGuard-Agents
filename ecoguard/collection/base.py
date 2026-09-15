"""The shared collector wrapper.

A collector fetches raw data and stores it. It does not detect, filter,
interpret or enrich — that is detection, and it reads these rows later.

The grid every collector writes against is `ecoguard.shared.cells`, re-exported
below for convenience.
"""

from __future__ import annotations

import logging
from typing import Any

from ecoguard.database.locks import single_flight
from ecoguard.database.repositories.collector_runs import log_finish, log_start
from ecoguard.database.repositories.observations import upsert_observations
# Re-exported rather than defined here. The cell is not a collection concept:
# detectors read it, the coordinator joins on it, and a repository already
# imported it from this module, which had collection sitting underneath the
# database layer. It lives in shared/cells.py now; these names stay importable
# so every collector keeps working.
from ecoguard.shared.cells import cell_for, service_area_cells  # noqa: F401

logger = logging.getLogger(__name__)


class BaseCollector:
    """Fetch, store, and record the outcome. Only fetch() differs per source."""

    source: str = ""

    def fetch(self) -> list[dict[str, Any]]:
        """Return raw records, each with cell_id, observed_at and payload.

        latitude and longitude are optional; a source that does not know where
        a reading came from leaves them out and location is stored as NULL.
        """
        raise NotImplementedError

    def run(self) -> None:
        """Never raises. A failed collector is one stale layer, not an outage.

        This is the single most important property of the collection layer: the
        scheduler thread must survive every provider outage, credential expiry
        and malformed response any of the four sources can produce.
        """
        try:
            with single_flight(f"collect_{self.source}") as acquired:
                if not acquired:
                    logger.info("%s collector: previous run still going, skipping tick", self.source)
                    return
                run_id = log_start(self.source)
                try:
                    written = upsert_observations(self.source, self.fetch())
                    log_finish(run_id, status="ok", rows_written=written)
                    logger.info("%s collector: %s new observations", self.source, written)
                except Exception as error:
                    log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
                    logger.exception("%s collector failed", self.source)
        except Exception:
            # The database itself is unreachable, so there is nowhere to write a
            # failed row. Log and return; the next tick tries again.
            logger.exception("%s collector could not reach the database", self.source)
