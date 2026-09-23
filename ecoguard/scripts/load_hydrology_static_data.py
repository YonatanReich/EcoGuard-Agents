"""Refreshing the Water Authority's reference data: basins, streams and markers."""

from __future__ import annotations

from ecoguard.collectors.flood.hydrology_static import (
    load_static_hydrology_layers,
)
from ecoguard.collectors.flood.hydrometric_stations import (
    load_hydrometric_station_catalog,
)
from ecoguard.collectors.flood.static_context import refresh_flood_static_context


def main() -> None:
    """Refresh the water reference data from the command line."""
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

    context = refresh_flood_static_context()
    print(
        "flood context: "
        f"{context['cells']:,} cells, "
        f"{context['hydrometric_stations']:,} hydrometric stations, "
        f"{context['rain_stations']:,} rain stations, "
        f"{context['station_topologies']:,} station routes, "
        f"{context['hydrometric_idf_links']:,} hydrometric-IDF links"
    )


if __name__ == "__main__":
    main()
