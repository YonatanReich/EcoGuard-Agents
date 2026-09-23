"""Normalize station observations into the detector's cell-based stream."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping


FLOW_THRESHOLD_STATUS_COMPLETE = "complete_thresholds"


def _grouped_records(
    rows: Iterable[dict[str, Any]],
    stations: Mapping[int, Mapping[str, Any]],
    value_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Return one deterministic record per cell and provider timestamp.

    The shared observations table has one identity per source/cell/time. Several
    stations can occupy one 5 km cell, so station readings are kept as a sorted
    list in that single payload rather than racing for the same unique key.
    """
    grouped: dict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        source_station_id = int(row["source_station_id"])
        station = stations.get(source_station_id)
        if not station or not station.get("cell_id"):
            # Unknown or unmapped stations are not part of the detector stream.
            continue
        key = (str(station["cell_id"]), row["observed_at"])
        item = {
            "source_station_id": source_station_id,
            "name_he": station.get("name_he"),
            "name_en": station.get("name_en"),
            "latitude": float(station["latitude"]),
            "longitude": float(station["longitude"]),
            "drainage_basin_id": station.get("drainage_basin_id"),
        }
        for field in value_fields:
            item[field] = row.get(field)
        for field in (
            "flow_start_water_level_m",
            "flow_threshold_2y_m3s",
            "flow_threshold_5y_m3s",
            "flow_threshold_10y_m3s",
            "flow_threshold_20y_m3s",
            "flow_threshold_50y_m3s",
            "flow_threshold_100y_m3s",
            "flow_threshold_status",
        ):
            if field in station:
                item[field] = station.get(field)
        grouped[key].append(item)

    records: list[dict[str, Any]] = []
    for (cell_id, observed_at), station_rows in sorted(grouped.items()):
        station_rows.sort(key=lambda item: item["source_station_id"])
        latitude = station_rows[0]["latitude"]
        longitude = station_rows[0]["longitude"]
        records.append(
            {
                "cell_id": cell_id,
                "latitude": latitude,
                "longitude": longitude,
                "observed_at": observed_at,
                "payload": {"stations": station_rows},
            }
        )
    return records


def hydrometric_signal_records(
    rows: Iterable[dict[str, Any]],
    stations: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Gauge readings in the shape the flood detector reads."""
    eligible_stations = {
        station_id: station
        for station_id, station in stations.items()
        if station.get("flow_threshold_status") == FLOW_THRESHOLD_STATUS_COMPLETE
    }
    return _grouped_records(
        rows,
        eligible_stations,
        ("discharge_m3s", "water_height_m"),
    )


def rainfall_signal_records(
    rows: Iterable[dict[str, Any]],
    stations: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rain gauge readings in the shape the flood detector reads."""
    return _grouped_records(rows, stations, ("rainfall_mm",))
