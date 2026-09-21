"""Collect numeric rain-rate cells from IMS ODIM HDF5 PPI products."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Iterable
from urllib.parse import urljoin

import h5py
import numpy as np
import requests
from requests_ntlm import HttpNtlmAuth
from rasterio.warp import transform
from sqlalchemy import text

from ecoguard.collection.base import BaseCollector, service_area_cells
from ecoguard.shared.grid import GridCell


SOURCE = "ims_radar_ppi"
INDEX_URL = "https://data.israel-meteo-service.org/ims/IMS_RADAR_RAW/"
COOKIE_ENVIRONMENT_VARIABLE = "IMS_RADAR_COOKIE"
USERNAME_ENVIRONMENT_VARIABLE = "IMS_RADAR_USERNAME"
PASSWORD_ENVIRONMENT_VARIABLE = "IMS_RADAR_PASSWORD"
REQUEST_TIMEOUT_SECONDS = 60
FRAME_PERIOD_MINUTES = 5.0
MIN_STORED_RATE_MM_H = 0.05
PPI_LINK = re.compile(
    r"href=[\"']([^\"']+\.PPI\.\d+\.h5)[\"']", re.IGNORECASE
)
PPI_TIMESTAMP = re.compile(r"\.(\d{14})\.PPI\.", re.IGNORECASE)

logger = logging.getLogger(__name__)


class RadarFormatError(ValueError):
    """The radar file is not the supported numeric ODIM PPI rain product."""


class RadarAuthenticationError(RuntimeError):
    """The configured IMS radar credentials were rejected."""


@dataclass(frozen=True)
class RadarFrame:
    observed_at: datetime
    projection: str
    xscale_m: float
    yscale_m: float
    data_mm_h: np.ndarray
    source_name: str

    @property
    def height(self) -> int:
        return int(self.data_mm_h.shape[0])

    @property
    def width(self) -> int:
        return int(self.data_mm_h.shape[1])


@dataclass(frozen=True)
class RadarCellMapping:
    cell_id: str
    latitude: float
    longitude: float
    row_start: int
    row_end: int
    column_start: int
    column_end: int


def _text_attribute(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.bytes_):
        return bytes(value).decode("utf-8")
    return str(value)


def read_radar_frame(content: bytes, *, source_name: str = "radar.h5") -> RadarFrame:
    """Read one ODIM PPI RATE array and apply its numeric scaling metadata."""
    try:
        with h5py.File(BytesIO(content), "r") as source:
            convention = _text_attribute(source.attrs.get("Conventions", ""))
            if not convention.startswith("ODIM_H5/"):
                raise RadarFormatError("radar file does not declare an ODIM convention")

            data_group = source["dataset1/data1"]
            dataset_what = source["dataset1/what"].attrs
            # IMS stores quantity/scaling on dataset1/what. Some ODIM writers
            # place the same metadata under data1/what, so accept both layouts.
            data_what = (
                data_group["what"].attrs if "what" in data_group else dataset_what
            )
            root_where = source["where"].attrs

            if _text_attribute(dataset_what.get("product", "")) != "PPI":
                raise RadarFormatError("radar product must be PPI")
            if _text_attribute(data_what.get("quantity", "")) != "RATE":
                raise RadarFormatError("PPI data quantity must be RATE")

            raw = np.asarray(data_group["data"], dtype=np.float32)
            if raw.ndim != 2 or raw.size == 0:
                raise RadarFormatError("radar RATE data must be a non-empty matrix")
            gain = float(data_what.get("gain", 1.0))
            offset = float(data_what.get("offset", 0.0))
            nodata = float(data_what.get("nodata", 65535.0))
            undetect = float(data_what.get("undetect", 0.0))
            invalid = raw == nodata
            values = raw * gain + offset
            values[raw == undetect] = 0.0
            values[invalid] = np.nan

            date = _text_attribute(dataset_what.get("startdate", dataset_what.get("date", "")))
            time = _text_attribute(dataset_what.get("starttime", dataset_what.get("time", "")))
            observed_at = datetime.strptime(date + time[:6], "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc
            )
            projection = _text_attribute(root_where["projdef"])
            xscale = float(root_where["xscale"])
            yscale = float(root_where["yscale"])
            if xscale <= 0 or yscale <= 0:
                raise RadarFormatError("radar pixel scales must be positive")
    except RadarFormatError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise RadarFormatError(f"invalid radar HDF5 structure: {error}") from error

    return RadarFrame(
        observed_at=observed_at,
        projection=projection,
        xscale_m=xscale,
        yscale_m=yscale,
        data_mm_h=values,
        source_name=source_name,
    )


def radar_geometry_signature(frame: RadarFrame) -> str:
    description = json.dumps(
        {
            "projection": frame.projection,
            "width": frame.width,
            "height": frame.height,
            "xscale_m": round(frame.xscale_m, 6),
            "yscale_m": round(frame.yscale_m, 6),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


def build_cell_mapping(
    frame: RadarFrame,
    cells: Iterable[GridCell] | None = None,
) -> list[RadarCellMapping]:
    """Map fixed 5 km cell footprints to radar row/column windows once."""
    selected = list(cells if cells is not None else service_area_cells())
    if not selected:
        return []
    xs, ys = transform(
        "EPSG:4326",
        frame.projection,
        [cell.longitude for cell in selected],
        [cell.latitude for cell in selected],
    )
    half_rows = max(1, math.ceil(2500.0 / frame.yscale_m))
    half_columns = max(1, math.ceil(2500.0 / frame.xscale_m))

    mappings: list[RadarCellMapping] = []
    for cell, x, y in zip(selected, xs, ys):
        column = math.floor(frame.width / 2 + x / frame.xscale_m)
        row = math.floor(frame.height / 2 - y / frame.yscale_m)
        row_start = max(0, row - half_rows)
        row_end = min(frame.height, row + half_rows + 1)
        column_start = max(0, column - half_columns)
        column_end = min(frame.width, column + half_columns + 1)
        if row_start >= row_end or column_start >= column_end:
            continue
        mappings.append(
            RadarCellMapping(
                cell_id=cell.cell_id,
                latitude=cell.latitude,
                longitude=cell.longitude,
                row_start=row_start,
                row_end=row_end,
                column_start=column_start,
                column_end=column_end,
            )
        )
    return mappings


def records_from_frame(
    frame: RadarFrame,
    mappings: Iterable[RadarCellMapping],
    *,
    include_dry_cells: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Aggregate numeric rates and keep dry heartbeats for active rain events."""
    dry_heartbeat_cells = set(include_dry_cells)
    records: list[dict[str, Any]] = []
    for mapping in mappings:
        window = frame.data_mm_h[
            mapping.row_start:mapping.row_end,
            mapping.column_start:mapping.column_end,
        ]
        valid = window[np.isfinite(window)]
        if valid.size == 0:
            continue
        mean_rate = float(np.mean(valid))
        max_rate = float(np.max(valid))
        if (
            max_rate < MIN_STORED_RATE_MM_H
            and mapping.cell_id not in dry_heartbeat_cells
        ):
            continue
        peak_index = int(np.nanargmax(window))
        peak_row, peak_column = np.unravel_index(peak_index, window.shape)
        global_row = mapping.row_start + int(peak_row)
        global_column = mapping.column_start + int(peak_column)
        peak_x = (global_column + 0.5 - frame.width / 2) * frame.xscale_m
        peak_y = (frame.height / 2 - global_row - 0.5) * frame.yscale_m
        peak_longitudes, peak_latitudes = transform(
            frame.projection,
            "EPSG:4326",
            [peak_x],
            [peak_y],
        )
        records.append(
            {
                "cell_id": mapping.cell_id,
                "latitude": mapping.latitude,
                "longitude": mapping.longitude,
                "observed_at": frame.observed_at,
                "payload": {
                    "rain_rate_mean_mm_h": round(mean_rate, 4),
                    "rain_rate_max_mm_h": round(max_rate, 4),
                    # This is the strongest rain pixel, not a confirmed flood
                    # location. The detector preserves that distinction.
                    "peak_latitude": round(float(peak_latitudes[0]), 6),
                    "peak_longitude": round(float(peak_longitudes[0]), 6),
                    "rainfall_mm": round(
                        mean_rate * FRAME_PERIOD_MINUTES / 60.0, 5
                    ),
                    "period_minutes": FRAME_PERIOD_MINUTES,
                    "valid_pixel_fraction": round(
                        float(valid.size / window.size), 4
                    ),
                    "source_file": frame.source_name,
                },
            }
        )
    return records


def _load_mapping(signature: str) -> list[RadarCellMapping]:
    from ecoguard.database.engine import Session

    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT cell_id, latitude, longitude, row_start, row_end,
                       column_start, column_end
                FROM radar_cell_mappings
                WHERE geometry_signature = :signature
                ORDER BY cell_id
                """
            ),
            {"signature": signature},
        ).mappings()
        return [RadarCellMapping(**dict(row)) for row in rows]


def _load_active_rain_cells() -> set[str]:
    """Keep sparse radar storage while retaining cells of open flood events."""
    from ecoguard.database.engine import Session

    with Session() as session:
        return set(
            session.execute(
                text(
                    """
                    SELECT DISTINCT unnest(cells) AS cell_id
                    FROM incidents
                    WHERE status = 'open'
                      AND 'flood' = ANY(hazards)
                    """
                )
            ).scalars()
        )


def _save_mapping(signature: str, mappings: list[RadarCellMapping]) -> None:
    if not mappings:
        return
    from ecoguard.database.engine import Session

    created_at = datetime.now(timezone.utc)
    rows = [
        {
            "signature": signature,
            "created_at": created_at,
            **mapping.__dict__,
        }
        for mapping in mappings
    ]
    with Session() as session:
        session.execute(
            text(
                """
                INSERT INTO radar_cell_mappings (
                  geometry_signature, cell_id, latitude, longitude,
                  row_start, row_end, column_start, column_end, created_at
                ) VALUES (
                  :signature, :cell_id, :latitude, :longitude,
                  :row_start, :row_end, :column_start, :column_end, :created_at
                )
                ON CONFLICT (geometry_signature, cell_id) DO NOTHING
                """
            ),
            rows,
        )
        session.commit()


def load_or_build_mapping(frame: RadarFrame) -> list[RadarCellMapping]:
    signature = radar_geometry_signature(frame)
    mappings = _load_mapping(signature)
    if mappings:
        return mappings
    mappings = build_cell_mapping(frame)
    _save_mapping(signature, mappings)
    return mappings


def _ppi_observed_at(name: str) -> datetime | None:
    match = PPI_TIMESTAMP.search(name)
    if match is None:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(
        tzinfo=timezone.utc
    )


def _all_ppi_links(index_html: str) -> list[tuple[datetime, str]]:
    links = {html.unescape(match) for match in PPI_LINK.findall(index_html)}
    parsed = [(_ppi_observed_at(name), name) for name in links]
    return sorted(
        (observed_at, name)
        for observed_at, name in parsed
        if observed_at is not None
    )


def ppi_links(index_html: str, *, limit: int = 6) -> list[str]:
    """Return the newest unique PPI files advertised by the IMS index."""
    if limit < 1:
        raise ValueError("limit must be positive")
    return [name for _, name in _all_ppi_links(index_html)[-limit:]]


def ppi_links_since(
    index_html: str,
    latest_cached_at: datetime | None,
    *,
    initial_frames: int = 6,
    overlap_frames: int = 2,
) -> list[str]:
    """Return every uncached frame plus a small idempotent overlap."""
    if initial_frames < 1:
        raise ValueError("initial_frames must be positive")
    if overlap_frames < 0:
        raise ValueError("overlap_frames must be non-negative")
    links = _all_ppi_links(index_html)
    if latest_cached_at is None:
        return [name for _, name in links[-initial_frames:]]
    if latest_cached_at.tzinfo is None or latest_cached_at.utcoffset() is None:
        raise ValueError("latest_cached_at must carry a UTC offset")
    latest_utc = latest_cached_at.astimezone(timezone.utc)
    first_new = next(
        (
            index
            for index, (observed_at, _) in enumerate(links)
            if observed_at > latest_utc
        ),
        len(links),
    )
    start = max(0, first_new - overlap_frames)
    return [name for _, name in links[start:]]


def _latest_cached_frame_time() -> datetime | None:
    from ecoguard.database.engine import Session

    with Session() as session:
        return session.execute(
            text("SELECT max(observed_at) FROM radar_frame_cache")
        ).scalar_one()


def _persist_batch(
    records: list[dict[str, Any]],
    frames: list[dict[str, Any]],
) -> int:
    """Cache observations and provider frame watermarks atomically."""
    from ecoguard.database.engine import Session
    from ecoguard.database.repositories.flood_observations import (
        upsert_flood_observations_in_session,
    )

    ingested_at = datetime.now(timezone.utc)
    with Session() as session:
        written = upsert_flood_observations_in_session(
            session,
            SOURCE,
            records,
            ingested_at=ingested_at,
        )
        if frames:
            session.execute(
                text(
                    """
                    INSERT INTO radar_frame_cache (
                      source_file, observed_at, cached_at
                    ) VALUES (
                      :source_file, :observed_at, :cached_at
                    )
                    ON CONFLICT (source_file) DO NOTHING
                    """
                ),
                [{**frame, "cached_at": ingested_at} for frame in frames],
            )
        session.commit()
    return written


class RadarPPICollector(BaseCollector):
    """Catch up every unseen PPI frame and store its numeric 5 km cells."""

    source = SOURCE

    def __init__(
        self,
        http_session: requests.Session | None = None,
        *,
        index_url: str = INDEX_URL,
        initial_frames: int = 6,
        overlap_frames: int = 2,
        cookie: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.http = http_session or requests.Session()
        self.index_url = index_url
        self.initial_frames = initial_frames
        self.overlap_frames = overlap_frames
        # IMS radar files are behind a web login. Keep the resulting session
        # cookie outside the source code and database, and never log its value.
        configured_cookie = (
            os.getenv(COOKIE_ENVIRONMENT_VARIABLE) if cookie is None else cookie
        )
        if configured_cookie:
            cookie_header = configured_cookie.strip()
            # Accept either the raw header value copied by the operator or a
            # complete "Cookie: ..." line to avoid a fragile setup step.
            if cookie_header.lower().startswith("cookie:"):
                cookie_header = cookie_header.split(":", 1)[1].strip()
            if cookie_header:
                self.http.headers["Cookie"] = cookie_header

        configured_username = (
            os.getenv(USERNAME_ENVIRONMENT_VARIABLE)
            if username is None
            else username
        )
        configured_password = (
            os.getenv(PASSWORD_ENVIRONMENT_VARIABLE)
            if password is None
            else password
        )
        if bool(configured_username) != bool(configured_password):
            raise ValueError(
                "IMS_RADAR_USERNAME and IMS_RADAR_PASSWORD must be set together"
            )
        if configured_username and configured_password:
            # HttpNtlmAuth performs the challenge-response exchange. The raw
            # password is never added to request headers or persisted in DB.
            self.http.auth = HttpNtlmAuth(
                configured_username.strip(), configured_password
            )

    @staticmethod
    def _require_success(response: requests.Response) -> None:
        """Raise a useful error without including authentication secrets."""
        if response.status_code in (401, 403):
            raise RadarAuthenticationError(
                "IMS radar NTLM authentication failed; check IMS_RADAR_USERNAME, "
                "IMS_RADAR_PASSWORD and the username domain"
            )
        response.raise_for_status()

    def _fetch_batch(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        index = self.http.get(self.index_url, timeout=REQUEST_TIMEOUT_SECONDS)
        self._require_success(index)
        records: list[dict[str, Any]] = []
        frames: list[dict[str, Any]] = []
        active_rain_cells = _load_active_rain_cells()
        mapping_cache: dict[str, list[RadarCellMapping]] = {}
        names = ppi_links_since(
            index.text,
            _latest_cached_frame_time(),
            initial_frames=self.initial_frames,
            overlap_frames=self.overlap_frames,
        )
        for name in names:
            response = self.http.get(
                urljoin(self.index_url, name), timeout=REQUEST_TIMEOUT_SECONDS
            )
            self._require_success(response)
            frame = read_radar_frame(response.content, source_name=name)
            frames.append(
                {"source_file": name, "observed_at": frame.observed_at}
            )
            signature = radar_geometry_signature(frame)
            mappings = mapping_cache.get(signature)
            if mappings is None:
                mappings = load_or_build_mapping(frame)
                mapping_cache[signature] = mappings
            records.extend(
                records_from_frame(
                    frame,
                    mappings,
                    include_dry_cells=active_rain_cells,
                )
            )
        return records, frames

    def fetch(self) -> list[dict[str, Any]]:
        records, _ = self._fetch_batch()
        return records

    def run(self) -> None:
        """Persist frame watermarks with observations so catch-up cannot skip."""
        from ecoguard.database.locks import single_flight
        from ecoguard.database.repositories.collector_runs import (
            log_finish,
            log_start,
        )

        try:
            with single_flight(f"collect_{self.source}") as acquired:
                if not acquired:
                    logger.info(
                        "%s collector: previous run still going, skipping tick",
                        self.source,
                    )
                    return
                run_id = log_start(self.source)
                try:
                    records, frames = self._fetch_batch()
                    written = _persist_batch(records, frames)
                    log_finish(run_id, status="ok", rows_written=written)
                    logger.info(
                        "%s collector: %s new observations from %s frames",
                        self.source,
                        written,
                        len(frames),
                    )
                except Exception as error:
                    log_finish(
                        run_id,
                        status="failed",
                        error=f"{type(error).__name__}: {error}",
                    )
                    logger.exception("%s collector failed", self.source)
        except Exception:
            logger.exception("%s collector could not reach the database", self.source)
