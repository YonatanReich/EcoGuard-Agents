"""Small in-process scheduler for weather-cache and national Current Risk refreshes."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from services.national_current_risk_scan_service import DEFAULT_OUTPUT_PATH, NationalCurrentRiskScanService
from services.open_meteo_hourly_client import OpenMeteoHourlyClient
from services.rolling_weather_cache import DEFAULT_CACHE_PATH, DEFAULT_GRID_PATH, RollingWeatherCache


DEFAULT_REFRESH_MINUTES = 180
DEFAULT_STATUS_PATH = Path("data/generated/fire_risk_refresh_status.json")


def configured_refresh_minutes() -> int:
    try:
        value = int(os.getenv("FIRE_RISK_REFRESH_INTERVAL_MINUTES", str(DEFAULT_REFRESH_MINUTES)))
    except ValueError:
        return DEFAULT_REFRESH_MINUTES
    return value if value >= 30 else DEFAULT_REFRESH_MINUTES


def _utc(value: datetime | None = None) -> datetime:
    selected = value or datetime.now(timezone.utc)
    if selected.tzinfo is None:
        raise ValueError("refresh timestamp must include a UTC offset")
    return selected.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _text(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class CurrentRiskRefreshOrchestrator:
    def __init__(
        self, *, weather_cache: RollingWeatherCache | None = None,
        weather_client_factory: Callable[[], Any] | None = None,
        scan_service: NationalCurrentRiskScanService | None = None,
        grid_path: Path | str = DEFAULT_GRID_PATH,
        snapshot_path: Path | str = DEFAULT_OUTPUT_PATH,
        status_path: Path | str = DEFAULT_STATUS_PATH,
        cadence_minutes: int | None = None,
    ):
        self.weather_cache = weather_cache or RollingWeatherCache(DEFAULT_CACHE_PATH)
        self.weather_client_factory = weather_client_factory or (lambda: OpenMeteoHourlyClient(batch_size=50))
        self.scan_service = scan_service or NationalCurrentRiskScanService(grid_path=grid_path)
        self.grid_path, self.snapshot_path, self.status_path = Path(grid_path), Path(snapshot_path), Path(status_path)
        self.cadence_minutes = cadence_minutes if cadence_minutes is not None else configured_refresh_minutes()
        if self.cadence_minutes < 30:
            raise ValueError("refresh cadence must be at least 30 minutes")
        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def refresh(self, evaluation_time: datetime | None = None) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            return {"status": "skipped_overlap", "scan_updated": False}
        started = _text()
        try:
            evaluation = _utc(evaluation_time)
            weather = self.weather_cache.update(
                grid_path=self.grid_path, client=self.weather_client_factory(), now=evaluation
            )
            if weather.get("status") not in {"success", "partial"}:
                result = {"status": "weather_unusable", "scan_updated": False, "weather": weather,
                          "started_at_utc": started, "completed_at_utc": _text(),
                          "cadence_minutes": self.cadence_minutes}
                _atomic_json(self.status_path, result); return result
            scan = self.scan_service.scan(evaluation)
            metadata = {"status": "success" if weather["status"] == "success" and scan["status"] == "success" else "partial",
                        "started_at_utc": started, "completed_at_utc": _text(),
                        "cadence_minutes": self.cadence_minutes, "weather_status": weather["status"],
                        "scan_status": scan["status"]}
            snapshot = {**scan, "refresh_metadata": metadata}
            _atomic_json(self.snapshot_path, snapshot)
            result = {"status": metadata["status"], "scan_updated": True, "weather": weather,
                      "scan_summary": scan["summary"], **metadata}
            _atomic_json(self.status_path, result)
            return result
        except Exception as error:
            result = {"status": "failed", "scan_updated": False, "error": type(error).__name__,
                      "started_at_utc": started, "completed_at_utc": _text(),
                      "cadence_minutes": self.cadence_minutes}
            _atomic_json(self.status_path, result)
            return result
        finally:
            self._run_lock.release()

    def latest_snapshot(self) -> dict[str, Any] | None:
        if not self.snapshot_path.exists():
            return None
        try:
            value = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) and isinstance(value.get("cells"), list) else None
        except (OSError, json.JSONDecodeError):
            return None

    def latest_status(self) -> dict[str, Any] | None:
        if not self.status_path.exists(): return None
        try:
            value = json.loads(self.status_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="current-risk-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive(): self._thread.join(timeout=5)

    def _loop(self) -> None:
        interval = self.cadence_minutes * 60
        while not self._stop.wait(interval):
            self.refresh()
