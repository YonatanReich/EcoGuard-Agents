"""The refresh loop scores the stored grid; it no longer fetches weather.

Fetching moved to the collection layer, so the orchestrator's only upstream is
the scan service. The blocking doubles below hang the *scan* where they used to
hang the weather update — same concurrency properties, one less provider.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from ecoguard.analyzers.emergency.fire.refresh_orchestrator import CurrentRiskRefreshOrchestrator


NOW = datetime(2026, 8, 29, 18, 45, tzinfo=timezone.utc)


def scan_result(status="success", unavailable=0):
    return {"status":status,"evaluation_time":"2026-08-29T18:00:00Z",
            "summary":{"total_active_cells":2,"evaluated_cells":2-unavailable,"unavailable_cells":unavailable,
                       "risk_level_counts":{"low":1,"medium":0,"high":1-unavailable},
                       "unavailable_reason_counts":{} if not unavailable else {"weather_history_incomplete":unavailable},
                       "highest_risk_cells":[]},"cells":[] if unavailable==2 else [{"cell_id":"a"}],
            "unavailable_cells":[],"semantics":"estimated_fire_risk_not_actual_fire_detection"}


class Scanner:
    def __init__(self, result=None, entered=None, release=None):
        self.result = result or scan_result(); self.calls = []
        self.entered, self.release = entered, release

    def scan(self, evaluation):
        self.calls.append(evaluation)
        if self.entered: self.entered.set()
        if self.release: self.release.wait(2)
        return self.result


def orchestrator(tmp_path, scanner=None):
    return CurrentRiskRefreshOrchestrator(
        scan_service=scanner or Scanner(), grid_path=tmp_path/"grid.sqlite",
        snapshot_path=tmp_path/"scan.json", status_path=tmp_path/"status.json",
        cadence_minutes=180,
    )


def test_successful_refresh_persists_latest_snapshot_and_metadata(tmp_path):
    scanner = Scanner(); service = orchestrator(tmp_path, scanner)
    result = service.refresh(NOW)
    assert result["status"] == "success" and result["scan_updated"] is True
    assert service.latest_snapshot()["refresh_metadata"]["scan_status"] == "success"
    assert scanner.calls == [datetime(2026, 8, 29, 18, tzinfo=timezone.utc)]


def test_a_partial_scan_is_still_published_with_its_unavailable_cells(tmp_path):
    service = orchestrator(tmp_path, Scanner(scan_result("partial", 1)))
    result = service.refresh(NOW)
    assert result["status"] == "partial" and result["scan_updated"] is True
    assert service.latest_snapshot()["summary"]["unavailable_cells"] == 1


def test_overlapping_refresh_is_skipped(tmp_path):
    entered, release = threading.Event(), threading.Event()
    scanner = Scanner(entered=entered, release=release)
    service = orchestrator(tmp_path, scanner); holder = []
    thread = threading.Thread(target=lambda: holder.append(service.refresh(NOW))); thread.start()
    assert entered.wait(1)
    overlap = service.refresh(NOW); release.set(); thread.join(2)
    assert overlap == {"status": "skipped_overlap", "scan_updated": False}
    assert len(scanner.calls) == 1 and holder[0]["scan_updated"] is True


def test_latest_snapshot_is_reused_without_rescanning(tmp_path):
    service = orchestrator(tmp_path); expected = scan_result()
    from ecoguard.analyzers.emergency.fire.refresh_orchestrator import _atomic_json
    _atomic_json(service.snapshot_path, expected)
    latest = service.latest_snapshot(now=NOW)
    assert latest["cells"] == expected["cells"]
    assert latest["refresh_metadata"]["snapshot_evaluation_time"] == expected["evaluation_time"]
    assert service.scan_service.calls == []


def test_default_cadence_is_conservative(monkeypatch, tmp_path):
    monkeypatch.delenv("FIRE_RISK_REFRESH_INTERVAL_MINUTES", raising=False)
    service = CurrentRiskRefreshOrchestrator(
        scan_service=Scanner(), grid_path=tmp_path/"grid",
        snapshot_path=tmp_path/"scan", status_path=tmp_path/"status",
    )
    assert service.cadence_minutes == 180


def test_start_returns_without_waiting_for_immediate_refresh_and_preserves_snapshot(tmp_path):
    entered, release = threading.Event(), threading.Event()
    service = orchestrator(tmp_path, Scanner(entered=entered, release=release))
    from ecoguard.analyzers.emergency.fire.refresh_orchestrator import _atomic_json
    _atomic_json(service.snapshot_path, scan_result())

    started = time.monotonic(); service.start(); elapsed = time.monotonic() - started
    assert elapsed < 0.2
    assert entered.wait(1)
    assert service.latest_snapshot(now=NOW)["cells"] == scan_result()["cells"]
    release.set(); service.stop()


def test_loop_runs_immediately_then_retains_configured_interval(tmp_path):
    service = orchestrator(tmp_path)
    service.refresh = MagicMock()
    stop = MagicMock()
    stop.wait.return_value = True
    service._stop = stop

    service._loop()

    service.refresh.assert_called_once_with()
    stop.wait.assert_called_once_with(180*60)


def test_snapshot_freshness_uses_evaluation_time_without_completed_refresh(tmp_path):
    service = orchestrator(tmp_path)
    snapshot = scan_result()

    fresh = service.with_freshness(snapshot, now=datetime(2026, 8, 29, 20, 59, tzinfo=timezone.utc))
    stale = service.with_freshness(snapshot, now=datetime(2026, 8, 29, 21, 1, tzinfo=timezone.utc))

    assert fresh["refresh_metadata"]["stale"] is False
    assert stale["refresh_metadata"]["stale"] is True
    assert fresh["refresh_metadata"]["last_successful_refresh_at_utc"] is None
    assert fresh["refresh_metadata"]["stale_after_minutes"] == 180


def test_snapshot_freshness_prefers_last_successful_refresh(tmp_path):
    service = orchestrator(tmp_path)
    completed = NOW.isoformat().replace("+00:00", "Z")
    snapshot = {**scan_result(), "refresh_metadata": {"status": "success", "completed_at_utc": completed}}

    result = service.with_freshness(snapshot, now=NOW+timedelta(minutes=179))

    assert result["refresh_metadata"]["stale"] is False
    assert result["refresh_metadata"]["last_successful_refresh_at_utc"] == completed
