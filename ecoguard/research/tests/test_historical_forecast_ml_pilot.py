from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

from research.datasets.build_historical_forecast_ml_pilot_dataset import (
    BatchedSingleRunClient, ForecastRunCache, ForecastRunUnavailableError,
    _archive_utc, acquire, complete_for_horizons, deterministic_select, fallback_runs,
    snapshot_plan,
)


UTC = timezone.utc


def test_archive_checkpoint_naive_timestamp_is_explicitly_utc():
    assert _archive_utc("2025-01-01T12:00").tzinfo == UTC


def rows():
    output=[]
    for year in (2024,2025,2026):
        for label in (0,1):
            for index in range(2):
                output.append({"sample_id":f"{year}-{label}-{index}","sample_type":"positive" if label else "negative",
                    "timestamp":f"{year}-06-{15+index:02d}T18:00:00Z","latitude":"31.8","longitude":"35.2",
                    "fire_label":str(label),"label_source":"test"})
    return output


def coverage_for(values):
    return {row["sample_id"]:(datetime.fromisoformat(row["timestamp"].replace("Z","+00:00"))-timedelta(days=8),
                               datetime.fromisoformat(row["timestamp"].replace("Z","+00:00"))) for row in values}


def test_deterministic_balanced_selection_and_exact_snapshots():
    source=rows(); coverage=coverage_for(source); cells=[("cell",31.8,35.2)]
    first=deterministic_select(source,coverage,cells,per_year_class=2); second=deterministic_select(source,coverage,cells,per_year_class=2)
    assert first==second and len(first)==12
    snapshots=snapshot_plan(first); assert len(snapshots)==36
    assert {row["horizon_hours"] for row in snapshots}=={3,6,12}
    assert all(datetime.fromisoformat(row["run_available_at"].replace("Z","+00:00")) <= datetime.fromisoformat(row["evaluation_time"].replace("Z","+00:00")) for row in snapshots)


def test_archive_start_is_preserved_without_blanket_march_exclusion():
    source=rows()
    for row in source:
        if row["sample_id"].startswith("2024-"):
            row["timestamp"]="2024-03-20T18:00:00Z"
    selected=deterministic_select(source,coverage_for(source),[("cell",31.8,35.2)],per_year_class=2)
    assert sum(row["year"]==2024 for row in selected)==4


def test_incomplete_current_history_is_rejected():
    row=rows()[0]; target=datetime.fromisoformat(row["timestamp"].replace("Z","+00:00"))
    assert not complete_for_horizons(row,{row["sample_id"]:(target-timedelta(hours=179),target)})


class Response:
    def __init__(self,payload,status=200,headers=None,text=""): self.payload,self.status_code,self.headers,self.text=payload,status,headers or {},text
    def json(self): return self.payload


def payload(run, latitude=31.8, longitude=35.2):
    times=[(run+timedelta(hours=i)).replace(tzinfo=None).isoformat(timespec="minutes") for i in range(48)]
    hourly={"time":times}
    for variable in ("temperature_2m","relative_humidity_2m","precipitation","wind_speed_10m","wind_gusts_10m"): hourly[variable]=[float(i) for i in range(48)]
    return {"latitude":latitude,"longitude":longitude,"timezone":"UTC","hourly":hourly}


class Session:
    def __init__(self,outcomes): self.outcomes=list(outcomes); self.calls=[]
    def get(self,*args,**kwargs): self.calls.append((args,kwargs)); value=self.outcomes.pop(0);


def test_multi_coordinate_batch_response_and_no_real_network():
    run=datetime(2025,1,1,tzinfo=UTC)
    class GoodSession:
        def __init__(self): self.calls=[]
        def get(self,*args,**kwargs): self.calls.append(kwargs); return Response([payload(run),payload(run,31.9,35.3)])
    session=GoodSession(); client=BatchedSingleRunClient(session=session,batch_size=2,minimum_interval_seconds=0)
    result=client.fetch_batch([(31.8,35.2),(31.9,35.3)],run)
    assert len(result)==2 and len(session.calls)==1
    assert session.calls[0]["params"]["latitude"]=="31.8,31.9"


def test_retry_429_is_bounded_and_honors_retry_after():
    run=datetime(2025,1,1,tzinfo=UTC); sleeps=[]
    class RetrySession:
        def __init__(self): self.calls=0
        def get(self,*args,**kwargs):
            self.calls+=1
            return Response({},429,{"Retry-After":"7"}) if self.calls==1 else Response(payload(run))
    session=RetrySession(); client=BatchedSingleRunClient(session=session,batch_size=1,minimum_interval_seconds=0,sleep=sleeps.append)
    assert len(client.fetch_batch([(31.8,35.2)],run))==1
    assert session.calls==2 and sleeps==[7.0]


def test_cache_resume_skips_completed_provider_request(tmp_path):
    run=datetime(2025,1,1,tzinfo=UTC); cache=ForecastRunCache(tmp_path/"cache.sqlite"); cache.initialize(); cache.save(31.8,35.2,run,{"run_time":run.isoformat(),"hourly":{}})
    snapshot={"sample_id":"a","latitude":"31.8","longitude":"35.2","run_initialization":run.isoformat()}
    class NoCallClient:
        batch_size=50; http_calls=0
        def fetch_batch(self,*args,**kwargs): raise AssertionError("provider must not be called")
    result=acquire([snapshot],cache,NoCallClient(),logger=lambda _:None)
    assert result["cache_hits"]==1 and result["http_calls"]==0 and result["status"]=="success"


def test_permanent_http_error_is_not_retried():
    run=datetime(2025,1,1,tzinfo=UTC)
    class PermanentSession:
        def __init__(self): self.calls=0
        def get(self,*args,**kwargs): self.calls+=1; return Response({},403)
    session=PermanentSession(); client=BatchedSingleRunClient(session=session,minimum_interval_seconds=0)
    with pytest.raises(Exception,match="permanent HTTP 403"): client.fetch_batch([(31.8,35.2)],run)
    assert session.calls==1


def snapshot(run, *, target_offset=12, sample_id="event", horizon=6):
    target=run+timedelta(hours=target_offset)
    return {"sample_id":sample_id,"horizon_hours":horizon,"latitude":"31.8","longitude":"35.2",
            "evaluation_time":(run+timedelta(hours=6)).isoformat(),
            "forecast_target_time":target.isoformat(),"forecast_target_hour":target.isoformat(),
            "run_initialization":run.isoformat()}


class RunClient:
    batch_size=50
    def __init__(self, missing=()): self.missing=set(missing); self.calls=[]; self.http_calls=0
    def fetch_batch(self, coordinates, run):
        self.calls.append(run); self.http_calls+=1
        if run in self.missing: raise ForecastRunUnavailableError(run)
        return [payload(run, *coordinate) for coordinate in coordinates]


def test_selected_run_exists_without_fallback(tmp_path):
    run=datetime(2025,1,2,tzinfo=UTC); cache=ForecastRunCache(tmp_path/"cache.sqlite"); client=RunClient()
    result=acquire([snapshot(run)],cache,client,logger=lambda _:None)
    assert result["status"]=="success" and client.calls==[run]
    assert cache.resolved_run(snapshot(run))==run


def test_missing_run_falls_back_and_stores_actual_run(tmp_path):
    run=datetime(2025,1,2,tzinfo=UTC); prior=run-timedelta(hours=6)
    case=snapshot(run); cache=ForecastRunCache(tmp_path/"cache.sqlite"); client=RunClient({run})
    result=acquire([case],cache,client,logger=lambda _:None)
    assert result["status"]=="success" and client.calls==[run,prior]
    assert cache.resolved_run(case)==prior
    assert not cache.has(31.8,35.2,run) and cache.has(31.8,35.2,prior)


def test_multiple_missing_runs_and_24_hour_limit(tmp_path):
    run=datetime(2025,1,3,tzinfo=UTC); missing={run-run_delta for run_delta in map(lambda h:timedelta(hours=h),(0,6,12))}
    case=snapshot(run,target_offset=6); cache=ForecastRunCache(tmp_path/"first.sqlite"); client=RunClient(missing)
    acquire([case],cache,client,logger=lambda _:None)
    assert cache.resolved_run(case)==run-timedelta(hours=18)

    all_runs={run-timedelta(hours=h) for h in (0,6,12,18,24)}
    other=snapshot(run,target_offset=6,sample_id="unavailable")
    cache2=ForecastRunCache(tmp_path/"second.sqlite"); client2=RunClient(all_runs)
    result=acquire([other],cache2,client2,logger=lambda _:None)
    assert client2.calls==[run-timedelta(hours=h) for h in (0,6,12,18,24)]
    assert cache2.resolved_run(other) is None and result["status"]=="partial"


def test_fallback_candidates_never_look_ahead():
    run=datetime(2025,1,2,6,tzinfo=UTC); evaluation=datetime(2025,1,2,11,tzinfo=UTC)
    candidates=fallback_runs(run,evaluation)
    assert run not in candidates
    assert candidates[0]==run-timedelta(hours=6)
    assert all(candidate+timedelta(hours=6)<=evaluation for candidate in candidates)


def test_known_unavailable_run_is_not_probed_again(tmp_path):
    run=datetime(2025,1,2,tzinfo=UTC); prior=run-timedelta(hours=6); cache=ForecastRunCache(tmp_path/"cache.sqlite")
    cache.initialize(); cache.record_run_status(run,"unavailable","test fixture")
    case=snapshot(run); client=RunClient()
    acquire([case],cache,client,logger=lambda _:None)
    assert client.calls==[prior] and cache.resolved_run(case)==prior


def test_target_hour_must_be_present_before_resolution(tmp_path):
    run=datetime(2025,1,2,tzinfo=UTC); prior=run-timedelta(hours=6); case=snapshot(run,target_offset=12)
    cache=ForecastRunCache(tmp_path/"cache.sqlite")
    class MissingTargetClient(RunClient):
        def fetch_batch(self, coordinates, selected_run):
            values=super().fetch_batch(coordinates,selected_run)
            if selected_run==run:
                target=datetime.fromisoformat(case["forecast_target_hour"]).replace(tzinfo=None).isoformat(timespec="minutes")
                index=values[0]["hourly"]["time"].index(target)
                for series in values[0]["hourly"].values(): series.pop(index)
            return values
    client=MissingTargetClient()
    acquire([case],cache,client,logger=lambda _:None)
    assert client.calls[0]==run and cache.resolved_run(case)==prior


def test_specific_missing_run_http_400_is_not_retried_by_client():
    run=datetime(2025,1,2,tzinfo=UTC)
    class MissingSession:
        def __init__(self): self.calls=0
        def get(self,*args,**kwargs):
            self.calls+=1
            return Response({},400,text='{"reason":"The requested model run is not available"}')
    session=MissingSession(); client=BatchedSingleRunClient(session=session,minimum_interval_seconds=0)
    with pytest.raises(ForecastRunUnavailableError): client.fetch_batch([(31.8,35.2)],run)
    assert session.calls==1
