"""Import a road GeoJSON file used by flood response-site discovery."""

from __future__ import annotations

import argparse

from ecoguard.collection.flood.road_network import replace_road_source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="GeoJSON FeatureCollection of road lines")
    parser.add_argument("--source", default="openstreetmap")
    args = parser.parse_args()
    count = replace_road_source(args.path, source=args.source)
    print(f"Imported {count} road segments from {args.source}")


if __name__ == "__main__":
    main()
