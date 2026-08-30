"""Build the offline 5 km fire-risk grid from existing local raster tiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.static_feature_store import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_SOURCE_DIRECTORY,
    StaticGridBuildError,
    build_static_grid_database,
)
from services.service_area import DEFAULT_SERVICE_AREA_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--source-directory", type=Path, default=DEFAULT_SOURCE_DIRECTORY)
    parser.add_argument("--service-area", type=Path, default=DEFAULT_SERVICE_AREA_PATH)
    args = parser.parse_args()
    try:
        summary = build_static_grid_database(
            args.output,
            source_directory=args.source_directory,
            service_area_path=args.service_area,
        )
    except (StaticGridBuildError, OSError) as error:
        print(f"Fire-risk grid build failed: {error}")
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
