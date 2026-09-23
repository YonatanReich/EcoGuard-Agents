"""Rebuild hydrometric-to-IDF rain-station links by drainage basin."""

from __future__ import annotations

from ecoguard.collectors.flood.rainfall_idf import (
    refresh_hydrometric_idf_basin_links_in_session,
)
from ecoguard.database.engine import Session


def main() -> None:
    """Rebuild the gauge-to-rain-station links from the command line."""
    with Session.begin() as session:
        links = refresh_hydrometric_idf_basin_links_in_session(session)
    print(f"Synchronized {links:,} same-basin hydrometric-to-IDF links.")


if __name__ == "__main__":
    main()
