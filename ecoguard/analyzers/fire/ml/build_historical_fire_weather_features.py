"""Adding the weather that preceded each historical fire.

Every value is taken from before the fire started, so nothing can be learned
from weather that had not happened yet.

Downloads are saved as they go, because the run takes hours and a restart
should not repeat what it already fetched."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from ecoguard.shared.weather_features import FEATURE_FIELDS, compute_features
from ecoguard.paths import GENERATED


SOURCE_NAME = "Open-Meteo Historical Weather API"
ARCHIVE_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
USER_AGENT = "EcoGuard-Agents historical-weather-builder/1.0"
TIMEZONE = "UTC"
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 4
RETRY_BASE_SECONDS = 2.0
RETRY_MAX_SECONDS = 30.0
REQUEST_PAUSE_SECONDS = 0.25
CHECKPOINT_FORMAT_VERSION = 1

INPUT_PATH = GENERATED / "firms_fire_rescue_matched_events_2023_2026.csv"
OUTPUT_PATH = GENERATED / "historical_fire_weather_features_2023_2026.csv"
CHECKPOINT_PATH = GENERATED / "historical_fire_weather_checkpoint"

HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)
CORE_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
)

IDENTITY_FIELDS = (
    "candidate_id",
    "start_timestamp",
    "centroid_latitude",
    "centroid_longitude",
    "settlement",
    "settlement_lamas_code",
    "official_month_support",
    "official_event_count",
    "firms_candidates_same_settlement_month",
    "ground_truth_status",
)
OUTPUT_FIELDS = IDENTITY_FIELDS + (
    "weather_source",
    "weather_collection_status",
    "weather_error",
) + FEATURE_FIELDS


class HistoricalWeatherError(RuntimeError):
    """Safe input, checkpoint, or provider failure."""


class ProviderError(HistoricalWeatherError):
    def __init__(self, category: str, *, transient: bool):
        """Carry the category of a provider failure."""
        super().__init__(category)
        self.category = category
        self.transient = transient


def _canonical_json(value: Any) -> str:
    """Stable JSON text, so unchanged data produces the same fingerprint."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_text(path: Path, text: str) -> None:
    """Write a file in one step, so a crash cannot leave it half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_utc_timestamp(value: object) -> datetime:
    """A stored timestamp as an aware time."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise HistoricalWeatherError("candidate timestamp is malformed") from None
    if parsed.tzinfo is None:
        raise HistoricalWeatherError("candidate timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def load_supported_candidates(path: Path = INPUT_PATH) -> list[dict[str, str]]:
    """The fire records this build can add weather to."""
    if not path.exists():
        raise HistoricalWeatherError(f"required generated input is missing: {path}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        raise HistoricalWeatherError(f"generated input is malformed: {path}") from None
    required = set(IDENTITY_FIELDS)
    if not rows or not required.issubset(rows[0]):
        raise HistoricalWeatherError("matched FIRMS input has an incompatible schema")
    selected = [row for row in rows if row.get("ground_truth_status") == "supported"]
    return sorted(selected, key=lambda row: (row["start_timestamp"], row["candidate_id"]))


def checkpoint_configuration(endpoint: str = ARCHIVE_ENDPOINT) -> dict[str, Any]:
    """What the saved progress was built with, so a changed setting invalidates it."""
    return {
        "endpoint": endpoint,
        "timezone": TIMEZONE,
        "hourly_variables": list(HOURLY_VARIABLES),
        "lookback_days": 7,
        "strictly_pre_event": True,
    }


class WeatherCheckpoint:
    def __init__(self, directory: Path, configuration: Mapping[str, Any]):
        """Open the saved progress for this build."""
        self.directory = directory
        self.entries = directory / "candidates"
        self.manifest = directory / "manifest.json"
        self.configuration = dict(configuration)

    def initialize(self) -> None:
        """Prepare the progress directory, discarding it if the settings changed."""
        expected = {
            "format_version": CHECKPOINT_FORMAT_VERSION,
            "configuration": self.configuration,
        }
        if self.manifest.exists():
            try:
                current = json.loads(self.manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                raise HistoricalWeatherError("weather checkpoint manifest is corrupted") from None
            if current != expected:
                raise HistoricalWeatherError("weather checkpoint is incompatible")
        elif self.directory.exists() and any(self.directory.iterdir()):
            raise HistoricalWeatherError("weather checkpoint has data but no valid manifest")
        else:
            _atomic_text(self.manifest, _canonical_json(expected))
        self.entries.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(candidate: Mapping[str, Any]) -> str:
        """A stable key for one record's weather."""
        identity = "|".join(
            str(candidate.get(field, ""))
            for field in ("candidate_id", "start_timestamp", "centroid_latitude", "centroid_longitude")
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]

    def _path(self, candidate: Mapping[str, Any]) -> Path:
        """Where one record's weather is saved."""
        return self.entries / f"{self._key(candidate)}.json"

    def save(self, candidate: Mapping[str, Any], weather: Mapping[str, Any]) -> None:
        """Keep one record's weather, so a restart does not re-download it."""
        payload = {
            "candidate": {
                field: str(candidate.get(field, ""))
                for field in ("candidate_id", "start_timestamp", "centroid_latitude", "centroid_longitude")
            },
            "weather": weather,
        }
        envelope = {
            "format_version": CHECKPOINT_FORMAT_VERSION,
            "sha256": hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest(),
            "payload": payload,
        }
        _atomic_text(self._path(candidate), _canonical_json(envelope))

    def load(self, candidate: Mapping[str, Any]) -> dict[str, Any] | None:
        """One record's saved weather, or None when it has not been fetched."""
        path = self._path(candidate)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            payload = envelope["payload"]
            expected_candidate = {
                field: str(candidate.get(field, ""))
                for field in ("candidate_id", "start_timestamp", "centroid_latitude", "centroid_longitude")
            }
            valid = (
                envelope.get("format_version") == CHECKPOINT_FORMAT_VERSION
                and envelope.get("sha256")
                == hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
                and payload.get("candidate") == expected_candidate
                and isinstance(payload.get("weather"), dict)
            )
            if not valid:
                raise ValueError
            return payload["weather"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise HistoricalWeatherError(
                f"weather checkpoint entry is corrupted: {candidate.get('candidate_id', '')}"
            ) from None


class OpenMeteoHistoricalClient:
    def __init__(
        self,
        *,
        endpoint: str = ARCHIVE_ENDPOINT,
        session: Any | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_attempts: int = MAX_RETRY_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        retry_logger: Callable[[str], None] = print,
    ):
        """Build the client for the historical weather archive."""
        self.endpoint = endpoint
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.retry_logger = retry_logger

    def fetch(self, latitude: float, longitude: float, event_time: datetime) -> dict[str, Any]:
        """The weather around one place and time."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": (event_time - timedelta(days=7)).date().isoformat(),
            "end_date": event_time.date().isoformat(),
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": TIMEZONE,
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.get(
                    self.endpoint,
                    params=params,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    transient = response.status_code == 429 or response.status_code >= 500
                    category = "rate limited" if response.status_code == 429 else (
                        "provider HTTP error" if transient else "invalid request"
                    )
                    raise ProviderError(category, transient=transient)
                try:
                    data = response.json()
                except (TypeError, ValueError):
                    raise ProviderError("malformed response", transient=False) from None
                return validate_hourly_response(data)
            except requests.Timeout:
                error = ProviderError("timeout", transient=True)
            except requests.RequestException:
                error = ProviderError("network error", transient=True)
            except ProviderError as caught:
                error = caught
            if not error.transient or attempt == self.max_attempts:
                raise error
            delay = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
            self.retry_logger(
                f"Weather retry: attempt {attempt + 1}/{self.max_attempts}; "
                f"reason={error.category}; delay={delay:.1f}s"
            )
            self.sleep(delay)
        raise ProviderError("provider error", transient=False)


def validate_hourly_response(data: Any) -> dict[str, Any]:
    """Reject a response that is missing the hours it claims to carry."""
    if not isinstance(data, dict) or data.get("timezone") not in {"GMT", "UTC"}:
        raise ProviderError("malformed response", transient=False)
    hourly = data.get("hourly")
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        raise ProviderError("malformed response", transient=False)
    size = len(hourly["time"])
    if not size:
        return {"status": "unavailable", "hourly": {"time": []}, "missing_variables": list(HOURLY_VARIABLES)}
    normalized: dict[str, Any] = {"time": hourly["time"]}
    missing = []
    for variable in HOURLY_VARIABLES:
        values = hourly.get(variable)
        if not isinstance(values, list) or len(values) != size:
            normalized[variable] = [None] * size
            missing.append(variable)
        else:
            normalized[variable] = values
    try:
        for value in normalized["time"]:
            datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise ProviderError("malformed response", transient=False) from None
    status = "partial" if missing else "success"
    return {"status": status, "hourly": normalized, "missing_variables": missing}


def _failed_row(candidate: Mapping[str, Any], category: str) -> dict[str, Any]:
    """A record marked as having no weather, and why."""
    row = {field: candidate.get(field, "") for field in IDENTITY_FIELDS}
    row.update({"weather_source": SOURCE_NAME, "weather_collection_status": "failed", "weather_error": category})
    row.update({field: None for field in FEATURE_FIELDS})
    return row


def build_feature_row(candidate: Mapping[str, Any], weather: Mapping[str, Any]) -> dict[str, Any]:
    """One record with its weather summarized into model inputs."""
    event_time = parse_utc_timestamp(candidate["start_timestamp"])
    features, status = compute_features(weather, event_time)
    row = {field: candidate.get(field, "") for field in IDENTITY_FIELDS}
    row.update({"weather_source": SOURCE_NAME, "weather_collection_status": status, "weather_error": ""})
    row.update(features)
    return row


def write_output(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Write the finished dataset to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def format_progress(completed: int, total: int, candidate: Mapping[str, Any], cached: int, elapsed: float) -> str:
    """A one-line progress report, with how much is left."""
    percentage = completed / total * 100 if total else 100.0
    hours, remainder = divmod(int(elapsed), 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"Progress: {completed} / {total} candidates ({percentage:.1f}%)\n"
        f"Candidate: {candidate.get('candidate_id', '')}\n"
        f"Timestamp: {candidate.get('start_timestamp', '')}\n"
        f"Weather rows cached: {cached}\n"
        f"Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}"
    )


def build_historical_weather_features(
    *,
    input_path: Path = INPUT_PATH,
    output_path: Path = OUTPUT_PATH,
    checkpoint_path: Path = CHECKPOINT_PATH,
    client: OpenMeteoHistoricalClient | None = None,
    progress_logger: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    request_pause_seconds: float = REQUEST_PAUSE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Add pre-event weather to every fire record."""
    candidates = load_supported_candidates(input_path)
    provider = client or OpenMeteoHistoricalClient()
    checkpoint = WeatherCheckpoint(checkpoint_path, checkpoint_configuration(provider.endpoint))
    checkpoint.initialize()
    started = clock()
    rows = []
    cached_count = 0
    for index, candidate in enumerate(candidates, start=1):
        weather = checkpoint.load(candidate)
        if weather is None:
            try:
                event_time = parse_utc_timestamp(candidate["start_timestamp"])
                weather = provider.fetch(
                    float(candidate["centroid_latitude"]),
                    float(candidate["centroid_longitude"]),
                    event_time,
                )
                checkpoint.save(candidate, weather)
                cached_count += 1
                rows.append(build_feature_row(candidate, weather))
            except ProviderError as error:
                rows.append(_failed_row(candidate, error.category))
            if request_pause_seconds and index < len(candidates):
                sleep(request_pause_seconds)
        else:
            cached_count += 1
            rows.append(build_feature_row(candidate, weather))
        progress_logger(format_progress(index, len(candidates), candidate, cached_count, clock() - started))
    rows.sort(key=lambda row: (str(row["start_timestamp"]), str(row["candidate_id"])))
    write_output(output_path, rows)
    return rows


def main() -> int:
    """Run the build from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--checkpoint-dir", type=Path, default=CHECKPOINT_PATH)
    args = parser.parse_args()
    try:
        rows = build_historical_weather_features(
            input_path=args.input,
            output_path=args.output,
            checkpoint_path=args.checkpoint_dir,
        )
    except HistoricalWeatherError as error:
        print(f"Historical weather build failed: {error}")
        return 1
    statuses: dict[str, int] = {}
    for row in rows:
        status = str(row["weather_collection_status"])
        statuses[status] = statuses.get(status, 0) + 1
    print(f"Historical weather rows: {len(rows)}; statuses: {statuses}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
