"""Load Water Authority drainage basins, streams and road-km markers.

Apply the database migrations first, then run from the repository root:

    alembic upgrade head
    python -m scripts.load_hydrology_static_layers

The command is safe to repeat. It downloads and validates all three files, then
replaces only layers whose canonical SHA-256 checksum changed.
"""

from __future__ import annotations

from ecoguard.collection.hydrology_static import load_static_hydrology_layers


def main() -> None:
    result = load_static_hydrology_layers()
    for layer, written in result.items():
        state = f"loaded {written:,} features" if written else "unchanged"
        print(f"{layer}: {state}")


if __name__ == "__main__":
    main()
