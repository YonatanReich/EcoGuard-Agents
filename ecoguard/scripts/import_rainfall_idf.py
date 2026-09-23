"""Import a validated flat IMS rainfall IDF CSV.

Usage:
    python -m ecoguard.scripts.import_rainfall_idf path/to/idf_flat.csv
"""

from __future__ import annotations

import argparse

from ecoguard.collectors.flood.rainfall_idf import (
    import_rainfall_idf_csv,
    parse_rainfall_idf_csv,
)


def main() -> None:
    """Import the rainfall intensity table from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="UTF-8 flat IDF CSV exported from IMS data")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the complete file without connecting to or changing the database",
    )
    args = parser.parse_args()

    if args.validate_only:
        rows = parse_rainfall_idf_csv(args.csv_path)
        print(
            f"Validated {len(rows):,} IDF values for "
            f"{len({row.source_station_id for row in rows}):,} rain stations."
        )
        return

    result = import_rainfall_idf_csv(args.csv_path)
    print(
        f"Imported {result['values']:,} IDF values for "
        f"{result['stations']:,} rain stations ({result['source_dataset']})."
    )


if __name__ == "__main__":
    main()
