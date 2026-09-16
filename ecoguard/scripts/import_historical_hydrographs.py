"""Cache Water Authority hydrograph exports and rebuild flood baselines.

Run this explicitly after the flood migration and static station registry have
been loaded. Historical observations remain separate from the real-time stream.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from ecoguard.collection.flood.historical_observations import (
    load_historical_hydrograph_files,
)
from ecoguard.collection.flood.static_context import (
    refresh_flood_station_baselines,
)


def run(paths: Sequence[str | Path]) -> dict[str, int]:
    history = load_historical_hydrograph_files(paths)
    return {
        **history,
        "monthly_baselines": refresh_flood_station_baselines(),
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Import Water Authority historical hydrograph CSV files and "
            "rebuild compact monthly flood baselines."
        )
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="CP1255 hydrograph CSV export(s)",
    )
    args = parser.parse_args(argv)
    result = run(args.files)
    print(
        "historical hydrographs: "
        f"{result['files_imported']:,} imported, "
        f"{result['files_unchanged']:,} unchanged, "
        f"{result['rows_written']:,} rows written, "
        f"{result['stations_seen']:,} source stations"
    )
    print(f"flood baselines: {result['monthly_baselines']:,} monthly rows")


if __name__ == "__main__":
    main()
