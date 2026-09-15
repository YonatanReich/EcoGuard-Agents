"""Download and cluster official historical NASA FIRMS observations for Israel.

This is an offline dataset builder. It does not modify or participate in the
production point-based fire-detection flow.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import io
import json
import math
import os
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

import requests
from dotenv import load_dotenv

from ecoguard.collection.fire.firms.client import FirmsProviderError
from ecoguard.paths import GENERATED


load_dotenv()

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov"
SOURCE_NAME = "NASA FIRMS"
USER_AGENT = "EcoGuard-Agents historical-firms-builder/1.0"
REQUEST_TIMEOUT_SECONDS = 60
REQUEST_PAUSE_SECONDS = 0.05
MAX_RETRY_ATTEMPTS = 4
RETRY_BASE_SECONDS = 2.0
RETRY_MAX_SECONDS = 30.0
MAX_API_DAY_RANGE = 5
CHECKPOINT_FORMAT_VERSION = 1

# A conservative rectangular query envelope. It reduces obvious distant
# observations but is not represented as, or used as, a political boundary.
ISRAEL_QUERY_BOUNDS = (34.2, 29.4, 35.9, 33.4)  # west, south, east, north

DEFAULT_START_DATE = date(2023, 1, 1)
DEFAULT_END_DATE = date.today()
DEFAULT_PRODUCTS = (
    "VIIRS_SNPP_SP",
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_SP",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
)
PRODUCT_FAMILIES = {
    "VIIRS_SNPP_SP": "SNPP",
    "VIIRS_SNPP_NRT": "SNPP",
    "VIIRS_NOAA20_SP": "NOAA20",
    "VIIRS_NOAA20_NRT": "NOAA20",
    "VIIRS_NOAA21_NRT": "NOAA21",
}

DEFAULT_MAX_SPATIAL_DISTANCE_KM = 1.5
DEFAULT_MAX_TEMPORAL_GAP_HOURS = 24.0
DEFAULT_MAX_INCIDENT_DURATION_HOURS = 72.0

RAW_OUTPUT_PATH = GENERATED / "firms_israel_hotspots_2023_2026.csv"
CLUSTER_OUTPUT_PATH = GENERATED / "firms_israel_candidate_incidents_2023_2026.csv"
CHECKPOINT_PATH = GENERATED / "firms_history_checkpoint"

RAW_FIELDS = (
    "hotspot_id",
    "latitude",
    "longitude",
    "acquisition_date",
    "acquisition_time",
    "acquisition_timestamp",
    "satellite",
    "instrument",
    "confidence",
    "frp",
    "daynight",
    "source",
    "source_product",
    "bright_ti4",
    "bright_ti5",
    "scan",
    "track",
    "version",
)

CLUSTER_FIELDS = (
    "candidate_id",
    "start_timestamp",
    "end_timestamp",
    "centroid_latitude",
    "centroid_longitude",
    "hotspot_count",
    "max_frp",
    "mean_frp",
    "satellites",
    "source_products",
    "duration_hours",
    "first_observation",
    "last_observation",
)


@dataclass(frozen=True)
class ProductAvailability:
    product: str
    minimum_date: date
    maximum_date: date


@dataclass(frozen=True)
class RequestWindow:
    product: str
    start: date
    days: int

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.days - 1)

    @property
    def key(self) -> str:
        value = f"{self.product}|{self.start.isoformat()}|{self.days}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class CheckpointError(RuntimeError):
    """Checkpoint is corrupt or incompatible with the requested build."""


class CheckpointStore:
    def __init__(self, directory: Path, configuration: Mapping[str, Any]):
        self.directory = directory
        self.windows_directory = directory / "windows"
        self.manifest_path = directory / "manifest.json"
        self.configuration = dict(configuration)

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def initialize(self) -> None:
        if self.manifest_path.exists():
            try:
                manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                raise CheckpointError("checkpoint manifest is corrupted") from None
            if (
                manifest.get("format_version") != CHECKPOINT_FORMAT_VERSION
                or manifest.get("configuration") != self.configuration
            ):
                raise CheckpointError(
                    "checkpoint is incompatible with the requested configuration"
                )
        elif self.directory.exists() and any(self.directory.iterdir()):
            raise CheckpointError("checkpoint directory has data but no valid manifest")
        else:
            self.windows_directory.mkdir(parents=True, exist_ok=True)
            self._atomic_json(
                self.manifest_path,
                {
                    "format_version": CHECKPOINT_FORMAT_VERSION,
                    "configuration": self.configuration,
                },
            )
        self.windows_directory.mkdir(parents=True, exist_ok=True)

    def _atomic_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_text(
                self._canonical_json(value), encoding="utf-8", newline="\n"
            )
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _window_path(self, window: RequestWindow) -> Path:
        return self.windows_directory / f"{window.key}.json"

    def save_window(
        self, window: RequestWindow, records: list[dict[str, Any]], malformed: int
    ) -> None:
        payload = {
            "window": {
                "key": window.key,
                "product": window.product,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
                "days": window.days,
            },
            "records": records,
            "malformed_rows": malformed,
        }
        envelope = {
            "format_version": CHECKPOINT_FORMAT_VERSION,
            "sha256": hashlib.sha256(
                self._canonical_json(payload).encode("utf-8")
            ).hexdigest(),
            "payload": payload,
        }
        self._atomic_json(self._window_path(window), envelope)

    def load_window(
        self, window: RequestWindow
    ) -> tuple[list[dict[str, Any]], int] | None:
        path = self._window_path(window)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            payload = envelope["payload"]
            checksum = hashlib.sha256(
                self._canonical_json(payload).encode("utf-8")
            ).hexdigest()
            metadata = payload["window"]
            if envelope.get("format_version") != CHECKPOINT_FORMAT_VERSION:
                raise ValueError
            if envelope.get("sha256") != checksum:
                raise ValueError
            if metadata != {
                "key": window.key,
                "product": window.product,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
                "days": window.days,
            }:
                raise ValueError
            records = payload["records"]
            malformed = payload["malformed_rows"]
            if not isinstance(records, list) or not isinstance(malformed, int):
                raise ValueError
            if any(
                not isinstance(record, dict)
                or set(record) != set(RAW_FIELDS)
                or record.get("source_product") != window.product
                for record in records
            ):
                raise ValueError
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise CheckpointError(
                f"checkpoint window is corrupted: {window.product} "
                f"{window.start} to {window.end}"
            ) from None
        return records, malformed


@dataclass
class _ActiveCluster:
    observations: list[dict[str, Any]]
    start: datetime
    latest: datetime
    latitude_sum: float
    longitude_sum: float
    bucket: tuple[int, int]
    version: int = 0
    active: bool = True

    @property
    def centroid_latitude(self) -> float:
        return self.latitude_sum / len(self.observations)

    @property
    def centroid_longitude(self) -> float:
        return self.longitude_sum / len(self.observations)


def parse_acquisition_timestamp(acquisition_date: object, acquisition_time: object) -> datetime:
    date_text = str(acquisition_date or "").strip()
    time_text = re.sub(r"\D", "", str(acquisition_time or "").strip()).zfill(4)
    if len(time_text) != 4:
        raise ValueError("invalid acquisition time")
    timestamp = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H%M")
    return timestamp.replace(tzinfo=timezone.utc)


def _optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite numeric value")
    return number


def _hotspot_id(record: Mapping[str, Any]) -> str:
    identity = "|".join(
        str(record.get(field, ""))
        for field in (
            "source_product",
            "satellite",
            "acquisition_timestamp",
            "latitude",
            "longitude",
        )
    )
    return "firms_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def normalize_firms_row(row: Mapping[str, Any], source_product: str) -> dict[str, Any] | None:
    """Normalize one official VIIRS CSV row; return None when malformed."""
    try:
        latitude = _optional_float(row.get("latitude"))
        longitude = _optional_float(row.get("longitude"))
        if latitude is None or longitude is None:
            return None
        west, south, east, north = ISRAEL_QUERY_BOUNDS
        if not (south <= latitude <= north and west <= longitude <= east):
            return None
        timestamp = parse_acquisition_timestamp(row.get("acq_date"), row.get("acq_time"))
        frp = _optional_float(row.get("frp"))
        record: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "acquisition_date": timestamp.date().isoformat(),
            "acquisition_time": timestamp.strftime("%H%M"),
            "acquisition_timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "satellite": str(row.get("satellite") or "").strip(),
            "instrument": str(row.get("instrument") or "").strip(),
            "confidence": str(row.get("confidence") or "").strip(),
            "frp": frp,
            "daynight": str(row.get("daynight") or "").strip(),
            "source": SOURCE_NAME,
            "source_product": source_product,
            "bright_ti4": _optional_float(row.get("bright_ti4")),
            "bright_ti5": _optional_float(row.get("bright_ti5")),
            "scan": _optional_float(row.get("scan")),
            "track": _optional_float(row.get("track")),
            "version": str(row.get("version") or "").strip(),
        }
    except (TypeError, ValueError):
        return None
    record["hotspot_id"] = _hotspot_id(record)
    return {field: record.get(field) for field in RAW_FIELDS}


def parse_firms_csv(csv_text: str, source_product: str) -> tuple[list[dict[str, Any]], int]:
    try:
        reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
        if reader.fieldnames is None:
            raise FirmsProviderError("malformed response")
        required = {"latitude", "longitude", "acq_date", "acq_time"}
        if not required.issubset(reader.fieldnames):
            raise FirmsProviderError("malformed response")
        records: list[dict[str, Any]] = []
        malformed = 0
        for row in reader:
            record = normalize_firms_row(row, source_product)
            if record is None:
                malformed += 1
            else:
                records.append(record)
        return records, malformed
    except csv.Error:
        raise FirmsProviderError("malformed response") from None


def deduplicate_hotspots(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {record["hotspot_id"]: record for record in records}
    return sorted(unique.values(), key=lambda row: (row["acquisition_timestamp"], row["hotspot_id"]))


def haversine_km(first: Mapping[str, Any], second: Mapping[str, Any]) -> float:
    lat1, lon1 = math.radians(float(first["latitude"])), math.radians(float(first["longitude"]))
    lat2, lon2 = math.radians(float(second["latitude"])), math.radians(float(second["longitude"]))
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _timestamp(record: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(str(record["acquisition_timestamp"]).replace("Z", "+00:00"))


def _cluster_centroid(observations: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "latitude": fmean(float(item["latitude"]) for item in observations),
        "longitude": fmean(float(item["longitude"]) for item in observations),
    }


def _build_candidate(observations: list[dict[str, Any]]) -> dict[str, Any]:
    observations.sort(key=lambda item: (item["acquisition_timestamp"], item["hotspot_id"]))
    start, end = _timestamp(observations[0]), _timestamp(observations[-1])
    centroid = _cluster_centroid(observations)
    frp_values = [float(item["frp"]) for item in observations if item.get("frp") is not None]
    identity = "|".join(item["hotspot_id"] for item in observations)
    return {
        "candidate_id": "firms_candidate_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
        "start_timestamp": start.isoformat().replace("+00:00", "Z"),
        "end_timestamp": end.isoformat().replace("+00:00", "Z"),
        "centroid_latitude": round(centroid["latitude"], 6),
        "centroid_longitude": round(centroid["longitude"], 6),
        "hotspot_count": len(observations),
        "max_frp": max(frp_values) if frp_values else None,
        "mean_frp": round(fmean(frp_values), 6) if frp_values else None,
        "satellites": ";".join(sorted({item["satellite"] for item in observations if item["satellite"]})),
        "source_products": ";".join(
            sorted({item["source_product"] for item in observations if item["source_product"]})
        ),
        "duration_hours": round((end - start).total_seconds() / 3600, 6),
        "first_observation": observations[0]["hotspot_id"],
        "last_observation": observations[-1]["hotspot_id"],
    }


def cluster_hotspots(
    records: Iterable[dict[str, Any]],
    *,
    max_spatial_distance_km: float = DEFAULT_MAX_SPATIAL_DISTANCE_KM,
    max_temporal_gap_hours: float = DEFAULT_MAX_TEMPORAL_GAP_HOURS,
    max_incident_duration_hours: float = DEFAULT_MAX_INCIDENT_DURATION_HOURS,
) -> list[dict[str, Any]]:
    """Greedily form conservative, bounded spatial-temporal components.

    A record joins the best eligible cluster when it is close to that cluster's
    current centroid, follows its latest observation within the temporal gap,
    and does not extend total cluster duration beyond the explicit cap.
    """
    if min(max_spatial_distance_km, max_temporal_gap_hours, max_incident_duration_hours) <= 0:
        raise ValueError("clustering parameters must be positive")
    ordered = deduplicate_hotspots(records)
    if not ordered:
        return []
    timed_records = [(record, _timestamp(record)) for record in ordered]

    # Cell dimensions conservatively cover every point within the Haversine
    # radius in the configured Israel envelope. Neighboring 3x3 cells are then
    # exact-filtered with Haversine distance, so bucketing never decides a match.
    angular_radius = max_spatial_distance_km / 6371.0088
    latitude_cell_degrees = math.degrees(angular_radius)
    maximum_absolute_latitude = max(abs(ISRAEL_QUERY_BOUNDS[1]), abs(ISRAEL_QUERY_BOUNDS[3]))
    minimum_cosine = math.cos(math.radians(maximum_absolute_latitude))
    longitude_cell_degrees = math.degrees(
        2 * math.asin(min(1.0, math.sin(angular_radius / 2) / minimum_cosine))
    )

    def bucket(latitude: float, longitude: float) -> tuple[int, int]:
        return (
            math.floor((latitude + 90.0) / latitude_cell_degrees),
            math.floor((longitude + 180.0) / longitude_cell_degrees),
        )

    temporal_gap = timedelta(hours=max_temporal_gap_hours)
    duration_limit = timedelta(hours=max_incident_duration_hours)
    clusters: list[_ActiveCluster] = []
    spatial_index: dict[tuple[int, int], set[int]] = {}
    expiry_heap: list[tuple[datetime, int, int]] = []

    def add_to_index(index: int, cell: tuple[int, int]) -> None:
        spatial_index.setdefault(cell, set()).add(index)

    def remove_from_index(index: int, cell: tuple[int, int]) -> None:
        indexes = spatial_index.get(cell)
        if indexes is None:
            return
        indexes.discard(index)
        if not indexes:
            del spatial_index[cell]

    def push_expiry(index: int) -> None:
        cluster = clusters[index]
        expires_at = min(cluster.latest + temporal_gap, cluster.start + duration_limit)
        heapq.heappush(expiry_heap, (expires_at, index, cluster.version))

    for record, current_time in timed_records:
        # Equality remains eligible, matching the previous > threshold checks.
        while expiry_heap and expiry_heap[0][0] < current_time:
            _, index, version = heapq.heappop(expiry_heap)
            cluster = clusters[index]
            if cluster.active and cluster.version == version:
                cluster.active = False
                remove_from_index(index, cluster.bucket)

        record_cell = bucket(float(record["latitude"]), float(record["longitude"]))
        nearby_indexes: set[int] = set()
        for latitude_offset in (-1, 0, 1):
            for longitude_offset in (-1, 0, 1):
                nearby_indexes.update(
                    spatial_index.get(
                        (
                            record_cell[0] + latitude_offset,
                            record_cell[1] + longitude_offset,
                        ),
                        (),
                    )
                )

        choices: list[tuple[float, int]] = []
        for index in nearby_indexes:
            cluster = clusters[index]
            gap_hours = (current_time - cluster.latest).total_seconds() / 3600
            duration_hours = (current_time - cluster.start).total_seconds() / 3600
            if gap_hours < 0 or gap_hours > max_temporal_gap_hours:
                continue
            if duration_hours > max_incident_duration_hours:
                continue
            distance = haversine_km(
                record,
                {
                    "latitude": cluster.centroid_latitude,
                    "longitude": cluster.centroid_longitude,
                },
            )
            if distance <= max_spatial_distance_km:
                choices.append((distance, index))

        if choices:
            index = min(choices)[1]
            cluster = clusters[index]
            old_bucket = cluster.bucket
            cluster.observations.append(record)
            cluster.latest = current_time
            cluster.latitude_sum += float(record["latitude"])
            cluster.longitude_sum += float(record["longitude"])
            cluster.version += 1
            cluster.bucket = bucket(
                cluster.centroid_latitude, cluster.centroid_longitude
            )
            if cluster.bucket != old_bucket:
                remove_from_index(index, old_bucket)
                add_to_index(index, cluster.bucket)
            push_expiry(index)
        else:
            index = len(clusters)
            clusters.append(
                _ActiveCluster(
                    observations=[record],
                    start=current_time,
                    latest=current_time,
                    latitude_sum=float(record["latitude"]),
                    longitude_sum=float(record["longitude"]),
                    bucket=record_cell,
                )
            )
            add_to_index(index, record_cell)
            push_expiry(index)

    return [_build_candidate(cluster.observations) for cluster in clusters]


class HistoricalFirmsClient:
    def __init__(
        self,
        api_key: str | None = None,
        session: requests.Session | None = None,
        *,
        max_retry_attempts: int = MAX_RETRY_ATTEMPTS,
        retry_base_seconds: float = RETRY_BASE_SECONDS,
        retry_max_seconds: float = RETRY_MAX_SECONDS,
        sleep_function=time.sleep,
        retry_logger=print,
    ):
        self.api_key = os.getenv("NASA_FIRMS_API_KEY") if api_key is None else api_key
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/csv"})
        if max_retry_attempts < 1:
            raise ValueError("max_retry_attempts must be at least one")
        self.max_retry_attempts = max_retry_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.sleep_function = sleep_function
        self.retry_logger = retry_logger

    def _get(self, path: str, *, request_description: str) -> str:
        if not self.api_key:
            raise FirmsProviderError("authentication error")
        url = f"{FIRMS_BASE_URL}{path}"
        for attempt in range(1, self.max_retry_attempts + 1):
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                return response.text
            except requests.exceptions.Timeout:
                category = "timeout"
                transient = True
            except requests.exceptions.HTTPError as error:
                status = getattr(error.response, "status_code", None)
                response_text = str(getattr(error.response, "text", "")).casefold()
                invalid_key = "invalid map_key" in response_text or "invalid map key" in response_text
                category = (
                    "authentication error"
                    if status in (401, 403) or (status == 400 and invalid_key)
                    else f"HTTP error (status {status or 'unknown'})"
                )
                transient = status in (408, 425, 429, 500, 502, 503, 504)
            except requests.exceptions.RequestException:
                category = "network error"
                transient = True
            if transient and attempt < self.max_retry_attempts:
                delay = min(
                    self.retry_max_seconds,
                    self.retry_base_seconds * (2 ** (attempt - 1)),
                )
                self.retry_logger(
                    f"Retry: attempt {attempt + 1}/{self.max_retry_attempts}; "
                    f"reason: {category}; request: {request_description}; "
                    f"backoff: {delay:.1f}s"
                )
                self.sleep_function(delay)
                continue
            raise FirmsProviderError(category) from None
        raise FirmsProviderError("network error")

    def discover_availability(self) -> dict[str, ProductAvailability]:
        text = self._get(
            f"/api/data_availability/csv/{self.api_key}/ALL",
            request_description="data availability",
        )
        try:
            rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
            discovered: dict[str, ProductAvailability] = {}
            for row in rows:
                product = str(row.get("data_id") or row.get("source") or "").strip()
                if product not in DEFAULT_PRODUCTS:
                    continue
                minimum = date.fromisoformat(str(row.get("min_date") or row.get("minimum_date")))
                maximum = date.fromisoformat(str(row.get("max_date") or row.get("maximum_date")))
                discovered[product] = ProductAvailability(product, minimum, maximum)
        except (csv.Error, TypeError, ValueError):
            raise FirmsProviderError("malformed response") from None
        if not discovered:
            raise FirmsProviderError("malformed response")
        return discovered

    def fetch_window(self, product: str, bounds: tuple[float, float, float, float], start: date, days: int) -> str:
        area = ",".join(str(value) for value in bounds)
        return self._get(
            f"/api/area/csv/{self.api_key}/{product}/{area}/{days}/{start.isoformat()}",
            request_description=(
                f"product {product}; window {start} to "
                f"{start + timedelta(days=days - 1)}"
            ),
        )


def plan_product_windows(
    availability: Mapping[str, ProductAvailability], start: date, end: date
) -> list[tuple[str, date, date]]:
    """Choose non-overlapping SP-first coverage separately for each satellite."""
    planned: list[tuple[str, date, date]] = []
    for family in ("SNPP", "NOAA20", "NOAA21"):
        products = [item for item in DEFAULT_PRODUCTS if PRODUCT_FAMILIES[item] == family]
        covered_until: date | None = None
        for product in products:  # SP appears before NRT in DEFAULT_PRODUCTS.
            available = availability.get(product)
            if available is None:
                continue
            window_start = max(start, available.minimum_date)
            if covered_until is not None:
                window_start = max(window_start, covered_until + timedelta(days=1))
            window_end = min(end, available.maximum_date)
            if window_start <= window_end:
                planned.append((product, window_start, window_end))
                covered_until = window_end
    return planned


def validate_product_plan(
    availability: Mapping[str, ProductAvailability],
    start: date,
    end: date,
    plans: Iterable[tuple[str, date, date]],
) -> None:
    """Reject windows outside official availability or with family gaps/overlaps."""
    plans = list(plans)
    for product, window_start, window_end in plans:
        available = availability.get(product)
        if (
            available is None
            or window_start < available.minimum_date
            or window_end > available.maximum_date
        ):
            raise FirmsProviderError(
                f"request plan exceeds official availability for {product}"
            )

    for family in ("SNPP", "NOAA20", "NOAA21"):
        family_availability = [
            item
            for product, item in availability.items()
            if PRODUCT_FAMILIES.get(product) == family
            and max(start, item.minimum_date) <= min(end, item.maximum_date)
        ]
        if not family_availability:
            continue
        expected_start = max(
            start, min(item.minimum_date for item in family_availability)
        )
        expected_end = min(end, max(item.maximum_date for item in family_availability))
        family_plans = sorted(
            (
                (window_start, window_end)
                for product, window_start, window_end in plans
                if PRODUCT_FAMILIES.get(product) == family
            ),
            key=lambda item: item[0],
        )
        if not family_plans or family_plans[0][0] != expected_start:
            raise FirmsProviderError(f"request plan has an availability gap for {family}")
        previous_end: date | None = None
        for window_start, window_end in family_plans:
            if previous_end is not None:
                if window_start <= previous_end:
                    raise FirmsProviderError(
                        f"request plan has overlapping products for {family}"
                    )
                if window_start != previous_end + timedelta(days=1):
                    raise FirmsProviderError(
                        f"request plan has an availability gap for {family}"
                    )
            previous_end = window_end
        if previous_end != expected_end:
            raise FirmsProviderError(f"request plan has an availability gap for {family}")


def _iter_api_windows(start: date, end: date) -> Iterable[tuple[date, int]]:
    current = start
    while current <= end:
        days = min(MAX_API_DAY_RANGE, (end - current).days + 1)
        yield current, days
        current += timedelta(days=days)


def build_request_windows(
    plans: Iterable[tuple[str, date, date]]
) -> list[RequestWindow]:
    return [
        RequestWindow(product, window_start, days)
        for product, product_start, product_end in plans
        for window_start, days in _iter_api_windows(product_start, product_end)
    ]


def checkpoint_configuration(
    *,
    start: date,
    end: date,
    windows: Iterable[RequestWindow],
    max_spatial_distance_km: float,
    max_temporal_gap_hours: float,
    max_incident_duration_hours: float,
) -> dict[str, Any]:
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "bounds": list(ISRAEL_QUERY_BOUNDS),
        "products": list(DEFAULT_PRODUCTS),
        "request_windows": [
            {
                "product": window.product,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
                "days": window.days,
            }
            for window in windows
        ],
        "max_api_day_range": MAX_API_DAY_RANGE,
        "max_spatial_distance_km": max_spatial_distance_km,
        "max_temporal_gap_hours": max_temporal_gap_hours,
        "max_incident_duration_hours": max_incident_duration_hours,
    }


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_progress(
    *,
    completed: int,
    total: int,
    window: RequestWindow,
    hotspot_count: int,
    elapsed_seconds: float,
    resumed: bool,
) -> str:
    percentage = completed / total * 100 if total else 100.0
    mode = "checkpoint" if resumed else "download"
    return (
        f"Progress: {completed} / {total} requests ({percentage:.1f}%)\n"
        f"Product: {window.product}\n"
        f"Window: {window.start} -> {window.end}\n"
        f"Hotspots collected: {hotspot_count}\n"
        f"Elapsed: {_format_elapsed(elapsed_seconds)}\n"
        f"Source: {mode}"
    )


def _load_complete_checkpoint(
    *,
    checkpoint_directory: Path,
    start: date,
    end: date,
    max_spatial_distance_km: float,
    max_temporal_gap_hours: float,
    max_incident_duration_hours: float,
    progress_logger,
    monotonic_function,
) -> tuple[list[dict[str, Any]], int] | None:
    manifest_path = checkpoint_directory / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        configuration = manifest["configuration"]
        window_items = configuration["request_windows"]
        expected_base = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "bounds": list(ISRAEL_QUERY_BOUNDS),
            "products": list(DEFAULT_PRODUCTS),
            "max_api_day_range": MAX_API_DAY_RANGE,
            "max_spatial_distance_km": max_spatial_distance_km,
            "max_temporal_gap_hours": max_temporal_gap_hours,
            "max_incident_duration_hours": max_incident_duration_hours,
        }
        if manifest.get("format_version") != CHECKPOINT_FORMAT_VERSION:
            raise CheckpointError("checkpoint manifest is corrupted")
        if any(configuration.get(key) != value for key, value in expected_base.items()):
            raise CheckpointError(
                "checkpoint is incompatible with the requested configuration"
            )
        windows = [
            RequestWindow(
                str(item["product"]),
                date.fromisoformat(str(item["start"])),
                int(item["days"]),
            )
            for item in window_items
        ]
        if any(
            window.days < 1
            or window.days > MAX_API_DAY_RANGE
            or item.get("end") != window.end.isoformat()
            for item, window in zip(window_items, windows)
        ):
            raise CheckpointError("checkpoint manifest is corrupted")
    except CheckpointError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise CheckpointError("checkpoint manifest is corrupted") from None

    store = CheckpointStore(checkpoint_directory, configuration)
    records: list[dict[str, Any]] = []
    malformed = 0
    started_at = monotonic_function()
    loaded: list[tuple[RequestWindow, list[dict[str, Any]], int]] = []
    for window in windows:
        cached = store.load_window(window)
        if cached is None:
            return None
        parsed, skipped = cached
        loaded.append((window, parsed, skipped))

    for request_index, (window, parsed, skipped) in enumerate(loaded, start=1):
        records.extend(parsed)
        malformed += skipped
        progress_logger(
            format_progress(
                completed=request_index,
                total=len(windows),
                window=window,
                hotspot_count=len({record["hotspot_id"] for record in records}),
                elapsed_seconds=monotonic_function() - started_at,
                resumed=True,
            )
        )
    unique_records = deduplicate_hotspots(records)
    progress_logger(
        f"Loaded {len(unique_records):,} unique hotspots from checkpoint."
    )
    return unique_records, malformed


def download_hotspots(
    client: HistoricalFirmsClient,
    start: date,
    end: date,
    *,
    checkpoint_directory: Path = CHECKPOINT_PATH,
    max_spatial_distance_km: float = DEFAULT_MAX_SPATIAL_DISTANCE_KM,
    max_temporal_gap_hours: float = DEFAULT_MAX_TEMPORAL_GAP_HOURS,
    max_incident_duration_hours: float = DEFAULT_MAX_INCIDENT_DURATION_HOURS,
    progress_logger=print,
    monotonic_function=time.monotonic,
) -> tuple[list[dict[str, Any]], dict[str, ProductAvailability], int]:
    if start > end:
        raise ValueError("start date must not follow end date")
    completed_checkpoint = _load_complete_checkpoint(
        checkpoint_directory=checkpoint_directory,
        start=start,
        end=end,
        max_spatial_distance_km=max_spatial_distance_km,
        max_temporal_gap_hours=max_temporal_gap_hours,
        max_incident_duration_hours=max_incident_duration_hours,
        progress_logger=progress_logger,
        monotonic_function=monotonic_function,
    )
    if completed_checkpoint is not None:
        records, malformed = completed_checkpoint
        return records, {}, malformed
    availability = client.discover_availability()
    plans = plan_product_windows(availability, start, end)
    if not plans:
        raise FirmsProviderError("no product data available")
    validate_product_plan(availability, start, end, plans)
    windows = build_request_windows(plans)
    configuration = checkpoint_configuration(
        start=start,
        end=end,
        windows=windows,
        max_spatial_distance_km=max_spatial_distance_km,
        max_temporal_gap_hours=max_temporal_gap_hours,
        max_incident_duration_hours=max_incident_duration_hours,
    )
    checkpoint = CheckpointStore(checkpoint_directory, configuration)
    checkpoint.initialize()
    records: list[dict[str, Any]] = []
    malformed = 0
    downloaded_windows = 0
    started_at = monotonic_function()
    for request_index, window in enumerate(windows, start=1):
        cached = checkpoint.load_window(window)
        resumed = cached is not None
        if cached is not None:
            parsed, skipped = cached
        else:
            if request_index > 1:
                time.sleep(REQUEST_PAUSE_SECONDS)
            try:
                text = client.fetch_window(
                    window.product, ISRAEL_QUERY_BOUNDS, window.start, window.days
                )
            except FirmsProviderError as error:
                raise FirmsProviderError(
                    f"{error}; product {window.product}; window "
                    f"{window.start} to {window.end}"
                ) from None
            parsed, skipped = parse_firms_csv(text, window.product)
            checkpoint.save_window(window, parsed, skipped)
            downloaded_windows += 1
        records.extend(parsed)
        malformed += skipped
        progress_logger(
            format_progress(
                completed=request_index,
                total=len(windows),
                window=window,
                hotspot_count=len({record["hotspot_id"] for record in records}),
                elapsed_seconds=monotonic_function() - started_at,
                resumed=resumed,
            )
        )
    unique_records = deduplicate_hotspots(records)
    origin = "checkpoint" if downloaded_windows == 0 else "checkpoint/download"
    progress_logger(
        f"Loaded {len(unique_records):,} unique hotspots from {origin}."
    )
    return unique_records, availability, malformed


def _atomic_write(path: Path, fields: tuple[str, ...], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_datasets(
    *,
    start: date = DEFAULT_START_DATE,
    end: date = DEFAULT_END_DATE,
    raw_output: Path = RAW_OUTPUT_PATH,
    cluster_output: Path = CLUSTER_OUTPUT_PATH,
    checkpoint_directory: Path = CHECKPOINT_PATH,
    max_spatial_distance_km: float = DEFAULT_MAX_SPATIAL_DISTANCE_KM,
    max_temporal_gap_hours: float = DEFAULT_MAX_TEMPORAL_GAP_HOURS,
    max_incident_duration_hours: float = DEFAULT_MAX_INCIDENT_DURATION_HOURS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, ProductAvailability], int]:
    client = HistoricalFirmsClient()
    hotspots, availability, malformed = download_hotspots(
        client,
        start,
        end,
        checkpoint_directory=checkpoint_directory,
        max_spatial_distance_km=max_spatial_distance_km,
        max_temporal_gap_hours=max_temporal_gap_hours,
        max_incident_duration_hours=max_incident_duration_hours,
    )
    print("Clustering hotspots...")
    clustering_started_at = time.monotonic()
    candidates = cluster_hotspots(
        hotspots,
        max_spatial_distance_km=max_spatial_distance_km,
        max_temporal_gap_hours=max_temporal_gap_hours,
        max_incident_duration_hours=max_incident_duration_hours,
    )
    print(
        f"Clustering complete: {len(candidates):,} candidate incidents in "
        f"{time.monotonic() - clustering_started_at:.1f}s."
    )
    _atomic_write(raw_output, RAW_FIELDS, hotspots)
    _atomic_write(cluster_output, CLUSTER_FIELDS, candidates)
    return hotspots, candidates, availability, malformed


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_parse_date, default=DEFAULT_START_DATE)
    parser.add_argument("--end", type=_parse_date, default=DEFAULT_END_DATE)
    parser.add_argument("--raw-output", type=Path, default=RAW_OUTPUT_PATH)
    parser.add_argument("--cluster-output", type=Path, default=CLUSTER_OUTPUT_PATH)
    parser.add_argument("--checkpoint-dir", type=Path, default=CHECKPOINT_PATH)
    parser.add_argument("--max-spatial-km", type=float, default=DEFAULT_MAX_SPATIAL_DISTANCE_KM)
    parser.add_argument("--max-temporal-gap-hours", type=float, default=DEFAULT_MAX_TEMPORAL_GAP_HOURS)
    parser.add_argument("--max-duration-hours", type=float, default=DEFAULT_MAX_INCIDENT_DURATION_HOURS)
    args = parser.parse_args()
    try:
        hotspots, candidates, availability, malformed = build_datasets(
            start=args.start,
            end=args.end,
            raw_output=args.raw_output,
            cluster_output=args.cluster_output,
            checkpoint_directory=args.checkpoint_dir,
            max_spatial_distance_km=args.max_spatial_km,
            max_temporal_gap_hours=args.max_temporal_gap_hours,
            max_incident_duration_hours=args.max_duration_hours,
        )
    except (CheckpointError, FirmsProviderError, ValueError) as error:
        print(f"Historical FIRMS build failed: {error}")
        return 1
    products = sorted({row["source_product"] for row in hotspots})
    print(f"Products used: {', '.join(products)}")
    print(f"Raw hotspots: {len(hotspots)}")
    print(f"Candidate incidents: {len(candidates)}")
    print(f"Malformed/out-of-bounds rows skipped: {malformed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
