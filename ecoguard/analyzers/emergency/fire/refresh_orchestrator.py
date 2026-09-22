"""Small in-process scheduler for the national Current Risk snapshot.

It used to fetch weather too, from its own Open-Meteo client into its own
SQLite cache. That was the second of three collection paths against the same
API; weather now arrives once, through the collection layer, and this only
scores what is already stored.
"""

from __future__ import annotations

from ecoguard.shared.activity import live_actor

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ecoguard.analyzers.emergency.fire.national_scan import DEFAULT_OUTPUT_PATH, NationalCurrentRiskScanService
from ecoguard.analyzers.emergency.fire.static_feature_store import DEFAULT_DATABASE_PATH as DEFAULT_GRID_PATH
from ecoguard.paths import GENERATED


DEFAULT_REFRESH_MINUTES = 180
DEFAULT_STATUS_PATH = GENERATED / "fire_risk_refresh_status.json"


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


def _parse_utc(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class CurrentRiskRefreshOrchestrator:
    def __init__(
        self, *,
        scan_service: NationalCurrentRiskScanService | None = None,
        grid_path: Path | str = DEFAULT_GRID_PATH,
        snapshot_path: Path | str = DEFAULT_OUTPUT_PATH,
        status_path: Path | str = DEFAULT_STATUS_PATH,
        cadence_minutes: int | None = None,
    ):
        self.scan_service = scan_service or NationalCurrentRiskScanService(grid_path=grid_path)
        self.grid_path, self.snapshot_path, self.status_path = Path(grid_path), Path(snapshot_path), Path(status_path)
        self.cadence_minutes = cadence_minutes if cadence_minutes is not None else configured_refresh_minutes()
        if self.cadence_minutes < 30:
            raise ValueError("refresh cadence must be at least 30 minutes")
        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @live_actor("analyzer.fire")
    def refresh(self, evaluation_time: datetime | None = None) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            return {"status": "skipped_overlap", "scan_updated": False}
        started = _text()
        try:
            evaluation = _utc(evaluation_time)
            scan = self.scan_service.scan(evaluation)
            metadata = {"status": "success" if scan["status"] == "success" else "partial",
                        "started_at_utc": started, "completed_at_utc": _text(),
                        "cadence_minutes": self.cadence_minutes,
                        "scan_status": scan["status"]}
            snapshot = {**scan, "refresh_metadata": metadata}
            _atomic_json(self.snapshot_path, snapshot)
            result = {"status": metadata["status"], "scan_updated": True,
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

    def with_freshness(
        self, snapshot: dict[str, Any], *, now: datetime | None = None,
    ) -> dict[str, Any]:
        """Add response-time freshness without modifying the persisted snapshot."""
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        metadata = dict(snapshot.get("refresh_metadata") or {})
        evaluation_text = snapshot.get("evaluation_time")
        completed_text = metadata.get("completed_at_utc")
        completed = _parse_utc(completed_text)
        evaluation = _parse_utc(evaluation_text)
        usable_refresh = metadata.get("status") in {"success", "partial"} and completed is not None
        reference = completed if usable_refresh else evaluation
        metadata.update({
            "snapshot_evaluation_time": evaluation_text,
            "last_successful_refresh_at_utc": completed_text if usable_refresh else None,
            "freshness_reference_time_utc": _text(reference) if reference else None,
            "stale_after_minutes": self.cadence_minutes,
            "stale": reference is None or current - reference > timedelta(minutes=self.cadence_minutes),
        })
        return {**snapshot, "refresh_metadata": metadata}

    def latest_snapshot(self, *, now: datetime | None = None) -> dict[str, Any] | None:
        if not self.snapshot_path.exists():
            return None
        try:
            value = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("cells"), list):
                return None
            return self.with_freshness(value, now=now)
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
        self.refresh()
        interval = self.cadence_minutes * 60
        while not self._stop.wait(interval):
            self.refresh()
