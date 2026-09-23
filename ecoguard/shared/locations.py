"""The list of places that are scanned, and which of them are switched on."""

import json
from pathlib import Path
from ecoguard.paths import ISRAEL_LOCATIONS


# Relative to the process working directory, so callers must run from the
# repository root. Pass an absolute path to load from anywhere else.
DEFAULT_LOCATIONS_FILE = ISRAEL_LOCATIONS


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