"""
Location Loader

Responsible for reading the list of predefined Israeli scan locations from
disk and filtering it down to the ones currently switched on.

This is the standalone read-only version of the same load that
MultiLocationCollectionService.load_locations performs internally. It exists
so callers can inspect or count the configured locations without spinning up
the collection service and its agents.

Each location record in the JSON file carries: name, region_type, latitude,
longitude, scan_radius_km and enabled.
"""

import json
from pathlib import Path


# Relative to the process working directory, so callers must run from the
# repository root. Pass an absolute path to load from anywhere else.
DEFAULT_LOCATIONS_FILE = Path("data/israel_locations.json")


def load_israel_locations(file_path=DEFAULT_LOCATIONS_FILE):
    """
    Load predefined Israel scan locations from a JSON file.

    Args:
        file_path (str | Path): Path to the Israel locations JSON file.

    Returns:
        list: Enabled Israel scan locations, in file order. A location with
            no "enabled" key counts as enabled, so the flag only needs to be
            set when switching a location off.

    Raises:
        FileNotFoundError: If the locations file is missing.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    with open(file_path, encoding="utf-8") as file:
        data = json.load(file)

    locations = data.get("locations", [])

    enabled_locations = []

    for location in locations:
        if location.get("enabled", True):
            enabled_locations.append(location)

    return enabled_locations