"""Offline SQLite store for fire-risk grid static predictors."""

from __future__ import annotations

import math
import os
import sqlite3
import statistics
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import rasterio
import numpy as np
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.windows import Window

from ecoguard.analyzers.fire.ml.build_historical_landcover_terrain_features import (
    DEM_VERSION,
    LAND_COVER_CLASSES,
    LAND_COVER_FEATURES,
    WORLDCOVER_VERSION,
    dem_tile,
    sample_land_cover,
    sample_slope_across_tiles,
    worldcover_tile,
)
from ecoguard.shared.grid import (
    GRID_RESOLUTION_KM,
    ISRAEL_RISK_BOUNDS,
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
    GridCell,
    generate_grid,
)
from ecoguard.shared.service_area import DEFAULT_SERVICE_AREA_PATH, ServiceArea
from ecoguard.paths import GENERATED


DEFAULT_DATABASE_PATH = GENERATED / "fire_risk_grid.sqlite"
DEFAULT_SOURCE_DIRECTORY = GENERATED / "static_environmental_sources"
PERMANENT_WATER_CODE = 80
LAND_OVERLAP_RECOVERY_THRESHOLD = 0.25
COASTAL_LAND_RECOVERY_THRESHOLD = 0.20
COASTAL_LAND_INSIDE_SHARE_THRESHOLD = 0.90
STATIC_MODEL_FEATURES = ("elevation_m", *LAND_COVER_FEATURES, "slope_degrees")


class StaticGridBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class StaticSample:
    elevation_m: float | None
    slope_degrees: float | None
    worldcover_class: int | None
    activation_method: str | None = None


class StaticSampler(Protocol):
    """Anything that can report terrain and land cover at a coordinate."""

    def sample(self, latitude: float, longitude: float) -> StaticSample:
        """Terrain and land cover at one coordinate."""

    def close(self) -> None:
        """Release whatever the sampler holds open."""


def select_representative_land_pixel(
    values: np.ndarray,
    service_mask: np.ndarray,
    transform,
    centroid_latitude: float,
    centroid_longitude: float,
    *,
    centroid_inside_service_area: bool = False,
) -> tuple[int, float, float] | None:
    """Return dominant land class and nearest valid land pixel for recovery."""
    if values.shape != service_mask.shape or values.size == 0:
        return None
    recognized = np.isin(values, tuple(LAND_COVER_CLASSES))
    valid_land = service_mask & recognized & (values != PERMANENT_WATER_CODE)
    all_land = recognized & (values != PERMANENT_WATER_CODE)
    service_land_fraction = int(valid_land.sum()) / values.size
    land_inside_share = int(valid_land.sum()) / int(all_land.sum()) if all_land.any() else 0.0
    existing_recovery = (
        centroid_inside_service_area
        and service_land_fraction >= LAND_OVERLAP_RECOVERY_THRESHOLD
    )
    coastal_recovery = (
        service_land_fraction >= COASTAL_LAND_RECOVERY_THRESHOLD
        and land_inside_share >= COASTAL_LAND_INSIDE_SHARE_THRESHOLD
    )
    if not (existing_recovery or coastal_recovery):
        return None

    land_values = values[valid_land]
    classes, counts = np.unique(land_values, return_counts=True)
    maximum = int(counts.max())
    # The smallest class code is a stable tie-breaker.
    dominant = int(classes[counts == maximum].min())

    rows, columns = np.nonzero(valid_land)
    xs = transform.c + (columns + 0.5) * transform.a
    ys = transform.f + (rows + 0.5) * transform.e
    longitude_scale = math.cos(math.radians(centroid_latitude))
    distances = (ys - centroid_latitude) ** 2 + ((xs - centroid_longitude) * longitude_scale) ** 2
    nearest = int(np.argmin(distances))
    return dominant, float(ys[nearest]), float(xs[nearest])


class LocalRasterSampler:
    """Read only existing WorldCover and GLO-90 tiles; never download data."""

    def __init__(
        self,
        source_directory: Path = DEFAULT_SOURCE_DIRECTORY,
        *,
        service_area_path: Path = DEFAULT_SERVICE_AREA_PATH,
        resolution_km: float = GRID_RESOLUTION_KM,
    ):
        """Open the raster sources, without reading them yet."""
        self.source_directory = Path(source_directory)
        self.service_area = ServiceArea(service_area_path)
        self.resolution_km = resolution_km
        self._stack = ExitStack()
        self._land: dict[str, object] = {}
        self._dem: dict[str, object] = {}

    def _open_land(self, latitude: float, longitude: float):
        """The land-cover raster covering this coordinate."""
        filename, _ = worldcover_tile(latitude, longitude)
        path = self.source_directory / "worldcover_2021" / filename
        if not path.exists():
            raise StaticGridBuildError(f"missing WorldCover tile: {path}")
        if filename not in self._land:
            self._land[filename] = self._stack.enter_context(rasterio.open(path))
        return self._land[filename]

    def _dem_for(self, latitude: float, longitude: float):
        """The elevation raster covering this coordinate."""
        # Reuse the historical builder's tile-edge convention.
        attempted: list[Path] = []
        for latitude_shift in (0.0, -0.5, 0.5):
            for longitude_shift in (0.0, -0.5, 0.5):
                filename, _ = dem_tile(latitude + latitude_shift, longitude + longitude_shift)
                path = self.source_directory / "copernicus_dem_glo90" / filename
                attempted.append(path)
                if not path.exists():
                    continue
                if filename not in self._dem:
                    self._dem[filename] = self._stack.enter_context(rasterio.open(path))
                dataset = self._dem[filename]
                if (
                    dataset.bounds.left <= longitude < dataset.bounds.right
                    and dataset.bounds.bottom <= latitude < dataset.bounds.top
                ):
                    return dataset
        names = ", ".join(sorted({path.name for path in attempted}))
        raise StaticGridBuildError(f"missing DEM coverage for {latitude:.6f},{longitude:.6f}; checked: {names}")

    def _recover_land_sample(self, latitude: float, longitude: float) -> tuple[int, float, float] | None:
        """Retry a land-cover reading from a neighbouring tile when one fails."""
        centroid_inside = self.service_area.contains_or_touches(latitude, longitude)
        latitude_half = self.resolution_km / LATITUDE_KM_PER_DEGREE / 2
        longitude_half = self.resolution_km / (
            LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * math.cos(math.radians(latitude))
        ) / 2
        bounds = (
            longitude - longitude_half,
            latitude - latitude_half,
            longitude + longitude_half,
            latitude + latitude_half,
        )
        datasets = {
            self._open_land(corner_latitude, corner_longitude)
            for corner_latitude in (bounds[1], latitude, bounds[3])
            for corner_longitude in (bounds[0], longitude, bounds[2])
        }
        values, transform = merge(tuple(datasets), bounds=bounds, nodata=0)
        values = values[0]
        service_mask = geometry_mask(
            [self.service_area.geometry],
            out_shape=values.shape,
            transform=transform,
            invert=True,
            all_touched=False,
        )
        return select_representative_land_pixel(
            values,
            service_mask,
            transform,
            latitude,
            longitude,
            centroid_inside_service_area=centroid_inside,
        )

    @staticmethod
    def _elevation(dataset, latitude: float, longitude: float) -> float | None:
        """Ground height at one coordinate, or None when it is not covered."""
        try:
            row, column = dataset.index(longitude, latitude)
            value = float(dataset.read(1, window=Window(column, row, 1, 1))[0, 0])
        except (IndexError, ValueError):
            return None
        return value if math.isfinite(value) else None

    def sample(self, latitude: float, longitude: float) -> StaticSample:
        """Terrain and land cover at one coordinate, read from the raster files."""
        land_cover = sample_land_cover(self._open_land(latitude, longitude), latitude, longitude)
        if land_cover is None:
            return StaticSample(None, None, land_cover, "inactive_unmapped")
        sample_latitude, sample_longitude = latitude, longitude
        activation_method = "centroid_land"
        if land_cover == PERMANENT_WATER_CODE:
            recovered = self._recover_land_sample(latitude, longitude)
            if recovered is None:
                return StaticSample(None, None, land_cover, "inactive_water")
            land_cover, sample_latitude, sample_longitude = recovered
            activation_method = "water_centroid_land_overlap"
        dem = self._dem_for(sample_latitude, sample_longitude)
        return StaticSample(
            elevation_m=self._elevation(dem, sample_latitude, sample_longitude),
            slope_degrees=sample_slope_across_tiles(sample_latitude, sample_longitude, self._dem_for),
            worldcover_class=land_cover,
            activation_method=activation_method,
        )

    def close(self) -> None:
        """Release the open raster files."""
        self._stack.close()


def _schema_sql() -> str:
    """The table definitions for the prepared terrain database."""
    flags = ",\n".join(f"{feature} INTEGER NOT NULL CHECK ({feature} IN (0, 1))" for feature in LAND_COVER_FEATURES)
    return f"""
    CREATE TABLE risk_grid_cells (
        cell_id TEXT PRIMARY KEY,
        grid_row INTEGER NOT NULL,
        grid_col INTEGER NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        active INTEGER NOT NULL CHECK (active IN (0, 1)),
        elevation_m REAL,
        slope_degrees REAL CHECK (slope_degrees IS NULL OR slope_degrees >= 0),
        worldcover_class INTEGER,
        {flags},
        dem_source_version TEXT NOT NULL,
        worldcover_source_version TEXT NOT NULL,
        built_at_utc TEXT NOT NULL,
        feature_status TEXT NOT NULL,
        feature_error TEXT,
        activation_method TEXT NOT NULL,
        UNIQUE(grid_row, grid_col)
    );
    CREATE INDEX idx_risk_grid_active ON risk_grid_cells(active);
    CREATE INDEX idx_risk_grid_lat_lon ON risk_grid_cells(latitude, longitude);
    CREATE INDEX idx_risk_grid_status ON risk_grid_cells(feature_status);
    """


def _row(cell: GridCell, sample: StaticSample, built_at: str) -> tuple:
    """One grid cell's terrain sample, as a database row."""
    active = int(sample.worldcover_class not in {None, PERMANENT_WATER_CODE})
    complete = active and sample.elevation_m is not None and sample.slope_degrees is not None
    status = "complete" if complete else ("inactive_water" if sample.worldcover_class == PERMANENT_WATER_CODE else "inactive_unmapped" if not active else "incomplete")
    error = None if status != "incomplete" else "missing elevation or slope"
    flags = tuple(int(active and sample.worldcover_class == code) for code in LAND_COVER_CLASSES)
    activation_method = sample.activation_method or (
        "centroid_land" if active else "inactive_water"
        if sample.worldcover_class == PERMANENT_WATER_CODE else "inactive_unmapped"
    )
    return (
        cell.cell_id, cell.grid_row, cell.grid_col, cell.latitude, cell.longitude, active,
        sample.elevation_m, sample.slope_degrees, sample.worldcover_class, *flags,
        DEM_VERSION, WORLDCOVER_VERSION, built_at, status, error, activation_method,
    )


def build_static_grid_database(
    database_path: Path = DEFAULT_DATABASE_PATH,
    *,
    source_directory: Path = DEFAULT_SOURCE_DIRECTORY,
    sampler: StaticSampler | None = None,
    bounds: tuple[float, float, float, float] = ISRAEL_RISK_BOUNDS,
    resolution_km: float = GRID_RESOLUTION_KM,
    service_area_path: Path = DEFAULT_SERVICE_AREA_PATH,
    built_at: str | None = None,
) -> dict:
    """Sample terrain and land cover for every cell and store the result.

    Run once. The analyzer then reads this instead of opening raster files on
    every request.
    """
    cells = generate_grid(bounds, resolution_km)
    if len({cell.cell_id for cell in cells}) != len(cells):
        raise StaticGridBuildError("duplicate cell_id generated")
    timestamp = built_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    owned_sampler = sampler is None
    raster_sampler = sampler or LocalRasterSampler(
        source_directory,
        service_area_path=service_area_path,
        resolution_km=resolution_km,
    )
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = database_path.with_suffix(database_path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(_schema_sql())
            columns = (
                "cell_id", "grid_row", "grid_col", "latitude", "longitude", "active",
                "elevation_m", "slope_degrees", "worldcover_class", *LAND_COVER_FEATURES,
                "dem_source_version", "worldcover_source_version", "built_at_utc",
                "feature_status", "feature_error", "activation_method",
            )
            placeholders = ",".join("?" for _ in columns)
            insert = f"INSERT INTO risk_grid_cells ({','.join(columns)}) VALUES ({placeholders})"
            for cell in cells:
                connection.execute(insert, _row(cell, raster_sampler.sample(cell.latitude, cell.longitude), timestamp))
            connection.commit()
            validate_database(connection)
        finally:
            connection.close()
        os.replace(temporary, database_path)
    finally:
        if owned_sampler:
            raster_sampler.close()
        if temporary.exists():
            temporary.unlink()
    return summarize_database(database_path, resolution_km=resolution_km)


def validate_database(connection: sqlite3.Connection) -> None:
    """Reject a prepared database that is incomplete or malformed."""
    duplicate = connection.execute("SELECT cell_id FROM risk_grid_cells GROUP BY cell_id HAVING COUNT(*) > 1").fetchone()
    if duplicate:
        raise StaticGridBuildError("duplicate cell_id persisted")
    invalid = connection.execute(
        f"""SELECT cell_id FROM risk_grid_cells WHERE active = 1 AND (
        latitude NOT BETWEEN -90 AND 90 OR longitude NOT BETWEEN -180 AND 180 OR
        elevation_m IS NULL OR slope_degrees IS NULL OR slope_degrees < 0 OR
        ({' + '.join(LAND_COVER_FEATURES)}) != 1) LIMIT 1"""
    ).fetchone()
    if invalid:
        raise StaticGridBuildError(f"invalid active static features for {invalid[0]}")


def summarize_database(path: Path, *, resolution_km: float = GRID_RESOLUTION_KM) -> dict:
    """A short description of what a prepared database contains."""
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("SELECT * FROM risk_grid_cells").fetchall()
    finally:
        connection.close()
    active = [row for row in rows if row["active"]]
    complete = [row for row in active if row["feature_status"] == "complete"]
    elevations = [row["elevation_m"] for row in complete]
    slopes = [row["slope_degrees"] for row in complete]
    distribution = Counter(LAND_COVER_CLASSES.get(row["worldcover_class"], "unmapped") for row in rows)
    def stats(values: list[float]) -> dict[str, float | None]:
        """The minimum, maximum and average of these values."""
        return {"min": min(values), "median": statistics.median(values), "max": max(values)} if values else {"min": None, "median": None, "max": None}
    return {
        "resolution_km": resolution_km,
        "total_cells": len(rows),
        "active_cells": len(active),
        "inactive_cells": len(rows) - len(active),
        "complete_cells": len(complete),
        "incomplete_active_cells": len(active) - len(complete),
        "inactive_water_cells": sum(row["feature_status"] == "inactive_water" for row in rows),
        "inactive_unmapped_cells": sum(row["feature_status"] == "inactive_unmapped" for row in rows),
        "approximate_active_area_km2": len(active) * resolution_km * resolution_km,
        "land_cover_distribution": dict(sorted(distribution.items())),
        "elevation_m": stats(elevations),
        "slope_degrees": stats(slopes),
    }
