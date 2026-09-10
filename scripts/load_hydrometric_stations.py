"""Synchronize Water Authority hydrometric station reference data.

Apply the database migrations first, then run from the repository root:

    alembic upgrade head
    python -m scripts.load_hydrometric_stations
"""

from __future__ import annotations

from ecoguard.collection.hydrometric_stations import load_hydrometric_station_catalog


def main() -> None:
    result = load_hydrometric_station_catalog()
    if not any(result.values()):
        print("hydrometric station catalog: unchanged")
        return
    print(
        "hydrometric station catalog: "
        f"{result['owners']:,} owners, "
        f"{result['stations']:,} stations, "
        f"{result['rain_links']:,} rain-station links synchronized"
    )


if __name__ == "__main__":
    main()
