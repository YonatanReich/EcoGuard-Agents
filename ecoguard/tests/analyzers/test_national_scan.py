from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ecoguard.analyzers.emergency.fire.national_scan import NationalCurrentRiskScanService
from ecoguard.shared.service_area import ServiceArea
from ecoguard.api.fire_risk_schemas import NationalRiskScanResponse


NOW = datetime(2026, 8, 29, 18, 37, tzinfo=timezone.utc)


def boundary(path):
    path.write_text('{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[34.5,30.5],[35.5,30.5],[35.5,32.5],[34.5,32.5],[34.5,30.5]]]}}]}', encoding="utf-8")
    return path


def grid(path):
    connection=sqlite3.connect(path)
    connection.execute("CREATE TABLE risk_grid_cells(cell_id TEXT PRIMARY KEY,latitude REAL,longitude REAL,active INTEGER)")
    connection.executemany("INSERT INTO risk_grid_cells VALUES(?,?,?,?)",[
        ("a",31.0,35.0,1),("b",32.0,35.0,1),("c",33.0,35.0,1),("inactive",30.0,35.0,0)])
    connection.commit(); connection.close()


class Builder:
    def __init__(self): self.calls=[]
    def build_for_cell(self, cell_id, evaluation_time):
        self.calls.append((cell_id,evaluation_time))
        if cell_id=="b": return {"status":"unavailable","reason":"weather_history_incomplete","features":None}
        return {"status":"success","features":{"cell":cell_id}}


class Predictor:
    def predict(self, features):
        score={"a":0.2,"c":0.8}[features["cell"]]
        return {"status":"ok","risk_score":score,"risk_level":"low" if score<0.5 else "high"}


def test_multi_cell_scan_tracks_unavailable_without_fabricated_risk(tmp_path):
    path=tmp_path/"grid.sqlite"; grid(path); builder=Builder()
    result=NationalCurrentRiskScanService(grid_path=path,feature_builder=builder,prediction_agent=Predictor(),service_area_path=boundary(tmp_path/"area.geojson")).scan(NOW)
    assert result["status"]=="partial"
    assert result["evaluation_time"]=="2026-08-29T18:00:00Z"
    assert [row["cell_id"] for row in result["cells"]]==["a"]
    assert result["unavailable_cells"]==[{"cell_id":"b","latitude":32.0,"longitude":35.0,"reason":"weather_history_incomplete"}]
    assert "risk_score" not in result["unavailable_cells"][0]
    assert result["summary"]["total_active_cells"]==2
    assert result["summary"]["evaluated_cells"]==1 and result["summary"]["unavailable_cells"]==1
    assert result["summary"]["risk_level_counts"]=={"low":1,"medium":0,"high":0}
    assert result["summary"]["highest_risk_cells"][0]["cell_id"]=="a"
    assert all(call[1]==datetime(2026,8,29,18,tzinfo=timezone.utc) for call in builder.calls)
    assert NationalRiskScanResponse.model_validate(result).summary.evaluated_cells==2


def test_supplied_timestamp_is_deterministic_and_persistence_matches(tmp_path):
    path=tmp_path/"grid.sqlite"; output=tmp_path/"scan.json"; grid(path)
    service=NationalCurrentRiskScanService(grid_path=path,feature_builder=Builder(),prediction_agent=Predictor(),service_area_path=boundary(tmp_path/"area.geojson"))
    first=service.scan(NOW); second=service.scan(NOW)
    assert first==second
    assert service.scan_and_save(NOW,output)==first and output.exists()


def test_naive_timestamp_is_rejected(tmp_path):
    path=tmp_path/"grid.sqlite"; grid(path)
    service=NationalCurrentRiskScanService(grid_path=path,feature_builder=Builder(),prediction_agent=Predictor(),service_area_path=boundary(tmp_path/"area.geojson"))
    import pytest
    with pytest.raises(Exception,match="UTC offset"): service.scan(datetime(2026,8,29,18))


def test_service_area_excludes_outside_before_feature_evaluation_and_includes_boundary(tmp_path):
    path=tmp_path/"grid.sqlite"; grid(path); builder=Builder()
    result=NationalCurrentRiskScanService(
        grid_path=path, feature_builder=builder, prediction_agent=Predictor(),
        service_area_path=boundary(tmp_path/"area.geojson"),
    ).scan(NOW)
    assert [cell_id for cell_id, _ in builder.calls] == ["a", "b"]
    assert "c" not in {row["cell_id"] for row in result["cells"] + result["unavailable_cells"]}
    area = ServiceArea(tmp_path/"area.geojson")
    assert area.contains_or_touches(30.5, 35.0)
    assert not area.contains_or_touches(33.0, 35.0)


def test_service_area_uses_shared_centroid_or_twenty_five_percent_overlap_rule(tmp_path):
    area = ServiceArea(boundary(tmp_path / "area.geojson"))
    assert area.includes_cell(31.0, 35.0)  # centroid inside
    assert area.includes_cell(31.0, 35.51)  # centroid outside, about 31% overlap
    assert not area.includes_cell(31.0, 35.52)  # centroid outside, about 12% overlap
    assert area.includes_cell(30.5, 35.0)  # centroid on boundary


def test_national_scan_uses_overlap_scope(tmp_path):
    path = tmp_path / "grid.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE risk_grid_cells(cell_id TEXT PRIMARY KEY,latitude REAL,longitude REAL,active INTEGER)")
    connection.executemany("INSERT INTO risk_grid_cells VALUES(?,?,?,1)", [
        ("inside", 31.0, 35.0), ("overlap", 31.0, 35.51), ("outside", 31.0, 35.6),
    ])
    connection.commit(); connection.close()
    service = NationalCurrentRiskScanService(
        grid_path=path, feature_builder=Builder(), prediction_agent=Predictor(),
        service_area_path=boundary(tmp_path / "area.geojson"),
    )
    assert [cell["cell_id"] for cell in service._active_cells()] == ["inside", "overlap"]
