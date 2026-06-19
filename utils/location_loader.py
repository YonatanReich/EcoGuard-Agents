"""
Location Loader

Utility functions for loading predefined scan locations.
"""

import json
from pathlib import Path


DEFAULT_LOCATIONS_FILE = Path("data/israel_locations.json")


def load_israel_locations(file_path=DEFAULT_LOCATIONS_FILE):
    """
    Load predefined Israel scan locations from a JSON file.

    Args:
        file_path (str | Path): Path to the Israel locations JSON file.

    Returns:
        list: Enabled Israel scan locations.
    """
    with open(file_path, encoding="utf-8") as file:
        data = json.load(file)

    locations = data.get("locations", [])

    enabled_locations = []

    for location in locations:
        if location.get("enabled", True):
            enabled_locations.append(location)

    return enabled_locations