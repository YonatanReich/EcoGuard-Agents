from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect

import numpy as np

from scripts.evaluate_historical_forecast_deterioration_pilot import (
    BASELINE_FEATURES, ENHANCED_FEATURES, FORECAST_FEATURES,
    build_evaluation_rows, evaluate, temporal_split,
)
from scripts.train_fire_prediction_landcover_terrain_models import FULL_FEATURES
from scripts.build_historical_environmental_features import PriorFirmsIndex


UTC = timezone.utc


def _hourly(start, hours=220, future_extreme_at=None):
    times=[start+timedelta(hours=i) for i in range(hours)]
    temperature=[20.0+i/1000 for i in range(hours)]
    if future_extreme_at in times: temperature[times.index(future_extreme_at)]=999.0
    return {"status":"success","hourly":{"time":[t.replace(tzinfo=None).isoformat(timespec="minutes") for t in times],
        "temperature_2m":temperature,"relative_humidity_2m":[40.0]*hours,"precipitation":[0.0]*hours,
        "wind_speed_10m":[10.0]*hours,"wind_gusts_10m":[15.0]*hours}}


class Checkpoint:
    def __init__(self, value): self.value=value
    def load(self, candidate): return self.value


class Cache:
    def __init__(self, runs, payloads): self.runs,self.payloads=runs,payloads
    def resolved_run(self, snapshot): return self.runs[int(snapshot["horizon_hours"])]
    def load(self, latitude, longitude, run): return self.payloads[run]


class Predictor:
    def __init__(self): self.payloads=[]
    def predict(self, values):
        assert tuple(values)==tuple(FULL_FEATURES)
        self.payloads.append(values)
        return {"status":"ok","risk_score":0.4,"risk_level":"medium"}


def test_feature_build_is_as_of_and_preserves_actual_fallback_run(monkeypatch):
    target=datetime(2025,6,20,18,tzinfo=UTC)
    sample={"sample_id":"p","timestamp":target.isoformat(),"latitude":"31.8","longitude":"35.2",
            "fire_label":"1","sample_type":"positive","year":"2025"}
    feature={**sample, **{name:"1" for name in FULL_FEATURES}}
    weather=_hourly(target-timedelta(hours=210),future_extreme_at=target)
    runs={h:target-timedelta(hours=h+6) for h in (12,6,3)}
    snapshots=[]; payloads={}
    for h,run in runs.items():
        evaluation=target-timedelta(hours=h)
        snapshots.append({**sample,"horizon_hours":str(h),"evaluation_time":evaluation.isoformat(),
                          "forecast_target_time":target.isoformat(),"forecast_target_hour":target.isoformat(),
                          "run_initialization":(run+timedelta(hours=6)).isoformat()})
        payloads[run]={"run_time":run.isoformat(),"hourly":_hourly(run,48)["hourly"]}
    monkeypatch.setattr("scripts.evaluate_historical_forecast_deterioration_pilot._weather_checkpoint",lambda label:Checkpoint(weather))
    predictor=Predictor()
    result=build_evaluation_rows([sample],snapshots,[feature],Cache(runs,payloads),predictor,PriorFirmsIndex([]))
    assert len(result)==1 and all(result[0][f"actual_run_initialization_t{h}h"]==runs[h].isoformat().replace("+00:00","Z") for h in runs)
    assert all(max(values["max_temperature_24h"],values["max_temperature_3d"])<999 for values in predictor.payloads)
    assert set(BASELINE_FEATURES).issubset(result[0]) and set(FORECAST_FEATURES).issubset(result[0])


def _evaluation_rows():
    rows=[]
    for year in (2024,2025,2026):
        for index in range(100):
            label=index%2
            row={"sample_id":f"{year}-{index}","timestamp":f"{year}-06-01T12:00:00Z","year":year,
                 "fire_label":label,"sample_type":"positive" if label else "negative"}
            row.update({name:float(label)+index/1000 for name in BASELINE_FEATURES})
            row.update({name:float(label)+(position%7)/100 for position,name in enumerate(FORECAST_FEATURES)})
            rows.append(row)
    return rows


def test_exact_temporal_split_and_deterministic_evaluation():
    rows=_evaluation_rows(); splits=temporal_split(rows)
    assert {name:len(values) for name,values in splits.items()}=={"train":100,"validation":100,"test":100}
    first,_,_=evaluate(rows); second,_,_=evaluate(rows)
    assert first==second
    assert set(first)=={"current_risk_only","current_risk_plus_forecast","deltas_enhanced_minus_baseline","split_counts","forecast_feature_missing_counts"}
    assert all(first["split_counts"][name]=={"rows":100,"positive":50,"negative":50} for name in splits)


def test_schema_and_no_network_or_production_coupling():
    assert len(BASELINE_FEATURES)==3 and len(FORECAST_FEATURES)==42 and len(ENHANCED_FEATURES)==45
    source=inspect.getsource(__import__("scripts.evaluate_historical_forecast_deterioration_pilot",fromlist=["x"]))
    assert "requests." not in source and "BatchedSingleRunClient" not in source
    assert "backend" not in source and "CombinedEarlyWarning" not in source
