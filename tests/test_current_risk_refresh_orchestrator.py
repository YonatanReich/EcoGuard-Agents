from __future__ import annotations

import threading
from datetime import datetime, timezone

from services.current_risk_refresh_orchestrator import CurrentRiskRefreshOrchestrator


NOW = datetime(2026, 8, 29, 18, 45, tzinfo=timezone.utc)


def scan_result(status="success", unavailable=0):
    return {"status":status,"evaluation_time":"2026-08-29T18:00:00Z",
            "summary":{"total_active_cells":2,"evaluated_cells":2-unavailable,"unavailable_cells":unavailable,
                       "risk_level_counts":{"low":1,"medium":0,"high":1-unavailable},
                       "unavailable_reason_counts":{} if not unavailable else {"weather_history_incomplete":unavailable},
                       "highest_risk_cells":[]},"cells":[] if unavailable==2 else [{"cell_id":"a"}],
            "unavailable_cells":[],"semantics":"estimated_fire_risk_not_actual_fire_detection"}


class Weather:
    def __init__(self,status="success",entered=None,release=None): self.status,self.calls=status,[]; self.entered,self.release=entered,release
    def update(self,**kwargs):
        self.calls.append(kwargs)
        if self.entered: self.entered.set()
        if self.release: self.release.wait(2)
        return {"status":self.status,"failed_nodes":1 if self.status=="partial" else 0}


class Scanner:
    def __init__(self,result=None): self.result=result or scan_result(); self.calls=[]
    def scan(self,evaluation): self.calls.append(evaluation); return self.result


def orchestrator(tmp_path,weather=None,scanner=None):
    return CurrentRiskRefreshOrchestrator(weather_cache=weather or Weather(),weather_client_factory=lambda:object(),
        scan_service=scanner or Scanner(),grid_path=tmp_path/"grid.sqlite",snapshot_path=tmp_path/"scan.json",
        status_path=tmp_path/"status.json",cadence_minutes=180)


def test_successful_refresh_persists_latest_snapshot_and_metadata(tmp_path):
    weather,scanner=Weather(),Scanner(); service=orchestrator(tmp_path,weather,scanner)
    result=service.refresh(NOW)
    assert result["status"]=="success" and result["scan_updated"] is True
    latest=service.latest_snapshot()
    assert latest["refresh_metadata"]["weather_status"]=="success"
    assert scanner.calls==[datetime(2026,8,29,18,tzinfo=timezone.utc)]
    assert weather.calls[0]["now"]==datetime(2026,8,29,18,tzinfo=timezone.utc)


def test_partial_weather_still_scans_and_preserves_unavailable_cells(tmp_path):
    scanner=Scanner(scan_result("partial",1)); service=orchestrator(tmp_path,Weather("partial"),scanner)
    result=service.refresh(NOW)
    assert result["status"]=="partial" and result["scan_updated"] is True
    assert service.latest_snapshot()["summary"]["unavailable_cells"]==1


def test_overlapping_refresh_is_skipped(tmp_path):
    entered,release=threading.Event(),threading.Event(); weather=Weather(entered=entered,release=release)
    service=orchestrator(tmp_path,weather,Scanner()); holder=[]
    thread=threading.Thread(target=lambda:holder.append(service.refresh(NOW))); thread.start(); assert entered.wait(1)
    overlap=service.refresh(NOW); release.set(); thread.join(2)
    assert overlap=={"status":"skipped_overlap","scan_updated":False}
    assert len(weather.calls)==1 and holder[0]["scan_updated"] is True


def test_latest_snapshot_is_reused_without_weather_or_scan(tmp_path):
    service=orchestrator(tmp_path); expected=scan_result();
    from services.current_risk_refresh_orchestrator import _atomic_json
    _atomic_json(service.snapshot_path,expected)
    assert service.latest_snapshot()==expected
    assert service.weather_cache.calls==[] and service.scan_service.calls==[]


def test_default_cadence_is_conservative(monkeypatch,tmp_path):
    monkeypatch.delenv("FIRE_RISK_REFRESH_INTERVAL_MINUTES",raising=False)
    service=CurrentRiskRefreshOrchestrator(weather_cache=Weather(),weather_client_factory=lambda:object(),scan_service=Scanner(),
        grid_path=tmp_path/"grid",snapshot_path=tmp_path/"scan",status_path=tmp_path/"status")
    assert service.cadence_minutes==180
