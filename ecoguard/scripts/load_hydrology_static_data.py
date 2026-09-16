"""Synchronize all Water Authority static hydrology reference data.

Apply the database migrations first, then run from the repository root:

    alembic upgrade head
    python -m ecoguard.scripts.load_hydrology_static_data

The command is safe to repeat. It synchronizes the three GeoJSON layers and
the hydrometric station catalog. Each collector independently skips database
writes when its source checksum has not changed.
"""

from __future__ import annotations

from ecoguard.collection.flood.hydrology_static import (
    load_static_hydrology_layers,
)
from ecoguard.collection.flood.historical_stations import (
    load_historical_station_registry,
)
from ecoguard.collection.flood.hydrometric_stations import (
    load_hydrometric_station_catalog,
)
from ecoguard.collection.flood.static_context import refresh_flood_static_context


def main() -> None:
    layer_result = load_static_hydrology_layers()
    for layer, written in layer_result.items():
        state = f"loaded {written:,} features" if written else "unchanged"
        print(f"{layer}: {state}")

    station_result = load_hydrometric_station_catalog()
    if not any(station_result.values()):
        print("hydrometric station catalog: unchanged")
    else:
        print(
            "hydrometric station catalog: "
            f"{station_result['owners']:,} owners, "
            f"{station_result['stations']:,} stations, "
            f"{station_result['rain_links']:,} rain-station links synchronized"
        )

    history_result = load_historical_station_registry()
    history_state = (
        f"loaded {history_result['historical_stations']:,} stations"
        if history_result["historical_stations"]
        else "unchanged"
    )
    print(
        "historical station registry: "
        f"{history_state}, "
        f"{history_result['automatic_links']:,} automatic links"
    )

    context = refresh_flood_static_context()
    print(
        "flood context: "
        f"{context['cells']:,} cells, "
        f"{context['hydrometric_stations']:,} hydrometric stations, "
        f"{context['rain_stations']:,} rain stations, "
        f"{context['station_topologies']:,} station routes, "
        f"{context['baselines']:,} monthly baselines"
    )


if __name__ == "__main__":
    main()
