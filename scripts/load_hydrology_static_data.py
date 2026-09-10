"""Synchronize all Water Authority static hydrology reference data.

Apply the database migrations first, then run from the repository root:

    alembic upgrade head
    python -m scripts.load_hydrology_static_data

The command is safe to repeat. It synchronizes the three GeoJSON layers and
the hydrometric station catalog. Each collector independently skips database
writes when its source checksum has not changed.
"""

from __future__ import annotations

from ecoguard.collection.hydrology_static import load_static_hydrology_layers
from ecoguard.collection.hydrometric_stations import (
    load_hydrometric_station_catalog,
)


def main() -> None:
    layer_result = load_static_hydrology_layers()
    for layer, written in layer_result.items():
        state = f"loaded {written:,} features" if written else "unchanged"
        print(f"{layer}: {state}")

    station_result = load_hydrometric_station_catalog()
    if not any(station_result.values()):
        print("hydrometric station catalog: unchanged")
        return
    print(
        "hydrometric station catalog: "
        f"{station_result['owners']:,} owners, "
        f"{station_result['stations']:,} stations, "
        f"{station_result['rain_links']:,} rain-station links synchronized"
    )


if __name__ == "__main__":
    main()
