"""Bootstrap or incrementally update the standalone rolling weather cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.open_meteo_hourly_client import OpenMeteoHourlyClient
from services.rolling_weather_cache import DEFAULT_CACHE_PATH, DEFAULT_GRID_PATH, RollingWeatherCache, WeatherCacheError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID_PATH)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    try:
        result = RollingWeatherCache(args.cache).update(
            grid_path=args.grid, client=OpenMeteoHourlyClient(batch_size=args.batch_size)
        )
    except (WeatherCacheError, OSError, ValueError) as error:
        print(f"Rolling weather cache update failed: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
